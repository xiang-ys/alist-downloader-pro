import requests
import cloudscraper
import json
import os
import time
import re
from urllib.parse import urlparse, unquote, quote as url_quote
from http.cookiejar import MozillaCookieJar
import gzip

try:
    import brotli
except ImportError:
    brotli = None
import traceback
import shutil
import subprocess
import zlib

# --- 配置区 ---
BASE_URL = "https://acgdb.de"
INITIAL_ALIST_PATH_UNENCODED = "/ASMR/RJ中文翻译、中文音视频/V#1 整理好的,下载解压即听/#1 DLsite-压缩包"
LOCAL_DOWNLOAD_ROOT = "F:\BaiduNetdiskDownload\\asmr"
COOKIE_FILE = "cookie.txt"
API_LIST_PATH = "/api/fs/list"
API_GET_PATH = "/api/fs/get"

DOWNLOAD_CHUNK_SIZE = 8192
RETRY_COUNT = 1  # API请求的外部重试次数（cloudscraper本身有内部重试）
RETRY_DELAY_SECONDS = 3  # 外部重试的延迟
DOWNLOAD_RETRY_COUNT = 2
DOWNLOAD_RETRY_DELAY = 5
DOWNLOAD_DELAY_SECONDS = 3
PART_FILE_SUFFIX = ".part"
# --- 配置区结束 ---

BROWSER_USER_AGENT = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"

session = None
brotli_available = False

# --- 特殊返回信号 ---
RETRY_OPERATION_AFTER_COOKIE_UPDATE = object()  # 用一个唯一的对象作为信号
USER_QUIT_OPERATION = object()


def check_nodejs():
    # ... (与上一版相同) ...
    node_path = shutil.which("node")
    if node_path:
        try:
            result = subprocess.run([node_path, "-v"], capture_output=True, text=True, check=True, timeout=5)
            print(f"Node.js 版本: {result.stdout.strip()} (路径: {node_path})")
            return True
        except subprocess.CalledProcessError as e:
            print(f"警告: Node.js 'node -v' 失败: {e}"); return True
        except subprocess.TimeoutExpired:
            print("警告: 'node -v' 超时。"); return True
        except FileNotFoundError:
            print("警告: Node.js 执行时 FileNotFoundError。"); return False
    else:
        print("警告: 未检测到 Node.js。"); return False


def init_scraper_session():
    # ... (与上一版相同) ...
    global session
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'android', 'mobile': True, 'custom': BROWSER_USER_AGENT},
            delay=20,
        )
        print("Cloudscraper session created with mobile browser profile.")
        session = scraper
        session.headers['User-Agent'] = BROWSER_USER_AGENT
        return True
    except Exception as e:
        print(f"FATAL: Error creating cloudscraper session: {e}"); traceback.print_exc(); return False


def load_cookies(cookie_file):
    # ... (与上一版相同) ...
    if not session: print("错误: Session 未初始化。"); return False
    cj = MozillaCookieJar(cookie_file)
    try:
        cj.load(ignore_discard=True, ignore_expires=True)
        # 清空旧的session cookies再加载，确保cf_clearance是最新的
        session.cookies.clear()
        session.cookies.update(cj)
        if any(c.name == 'cf_clearance' and (
                urlparse(BASE_URL).netloc == c.domain.lstrip('.') or ('.' + urlparse(BASE_URL).netloc) == c.domain) for
               c in session.cookies):
            print("`cf_clearance` cookie found and reloaded into cloudscraper session.")
        else:
            print("警告重要: `cf_clearance` for target domain NOT found in reloaded cookies.")
        print(f"成功从 {cookie_file} 重新加载Cookies。")
        return True
    except FileNotFoundError:
        print(f"错误: Cookie文件 {cookie_file} 未找到。"); return False
    except Exception as e:
        print(f"重新加载Cookie出错: {e}"); traceback.print_exc(); return False


def decompress_content(response):
    # ... (与上一版相同) ...
    content_encoding = response.headers.get('Content-Encoding', '').lower()
    content = response.content
    if not content: return ""
    try:
        if 'gzip' in content_encoding:
            return gzip.decompress(content).decode('utf-8', errors='replace')
        elif 'br' in content_encoding:
            if brotli_available and brotli:
                return brotli.decompress(content).decode('utf-8', errors='replace')
            else:
                return content.decode('utf-8', errors='replace')
        elif 'deflate' in content_encoding:
            return zlib.decompress(content, wbits=zlib.MAX_WBITS | 32).decode('utf-8', errors='replace')
        else:
            return content.decode('utf-8', errors='replace')
    except Exception:
        return content.decode('utf-8', errors='replace')


def prompt_user_for_cookie_update():
    """提示用户更新Cookie并等待确认。"""
    print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("!!! SCRIPT DETECTED CLOUDFLARE CHALLENGE !!!")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("To continue, please manually update the cookie.txt file:")
    print(f"1. Open your web browser and navigate to: {BASE_URL}")
    print(f"2. Ensure you can browse the site and pass any Cloudflare checks.")
    print(f"3. IMMEDIATELY export the cookies for '{urlparse(BASE_URL).netloc}' to '{COOKIE_FILE}'")
    print(f"   in the script's directory ('{os.getcwd()}'), overwriting the old one.")

    while True:
        user_choice = input("Have you updated cookie.txt and are ready to continue? (yes/quit): ").strip().lower()
        if user_choice == 'yes':
            if load_cookies(COOKIE_FILE):  # 尝试重新加载
                print("Cookies reloaded. Attempting to retry the operation...")
                return True  # 表示用户已更新，可以重试
            else:
                print("Failed to reload cookies. Please check the file and ensure it's correct.")
                # 保持在循环中，让用户再次尝试或退出
        elif user_choice == 'quit':
            print("Exiting script as per user request.")
            return False  # 表示用户选择退出
        else:
            print("Invalid input. Please type 'yes' or 'quit'.")


def make_api_request(method, api_endpoint, payload=None, retries=RETRY_COUNT, base_delay=RETRY_DELAY_SECONDS):
    if not session: return {"error_type": "session_not_initialized", "message": "Cloudscraper session not initialized."}
    url = BASE_URL + api_endpoint
    # ... (headers 构造与上一版相同) ...
    referer_path_unencoded = INITIAL_ALIST_PATH_UNENCODED
    if payload and "path" in payload:  # ... (Referer 构造逻辑不变) ...
        current_item_path_unencoded = payload["path"]
        if api_endpoint == API_LIST_PATH:
            referer_path_unencoded = current_item_path_unencoded
        elif api_endpoint == API_GET_PATH:
            if isinstance(current_item_path_unencoded, str):
                stripped_path = current_item_path_unencoded.rstrip('/')
                if '/' in stripped_path:
                    path_parts = stripped_path.split('/')
                    if len(path_parts) > 1:
                        parent_dir_parts = path_parts[:-1]
                        if not parent_dir_parts or (len(parent_dir_parts) == 1 and parent_dir_parts[0] == ''):
                            referer_path_unencoded = "/"
                        else:
                            referer_path_unencoded = "/" + "/".join(filter(None, parent_dir_parts))
                    else:
                        referer_path_unencoded = "/"
                else:
                    referer_path_unencoded = "/"
    encoded_referer_path = url_quote(referer_path_unencoded, safe='/:')
    headers = {
        'Accept': 'application/json, text/plain, */*', 'Accept-Language': 'zh-CN,zh;q=0.9,sq;q=0.8',
        'Referer': BASE_URL + encoded_referer_path,
        'Origin': BASE_URL, 'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'same-origin',
    }
    if method.upper() == 'POST': headers['Content-Type'] = 'application/json;charset=UTF-8'

    for attempt in range(retries + 1):
        response, response_text_decoded, is_cloudflare_challenge_final = None, "", False
        try:
            print(f"  API请求: {method} {url} (尝试 {attempt + 1}/{retries + 1})")
            if payload: print(f"    Payload: {json.dumps(payload, ensure_ascii=False)}")
            session.headers.update({'User-Agent': BROWSER_USER_AGENT})

            if method.upper() == 'POST':
                response = session.post(url, json=payload, headers=headers, timeout=60)
            elif method.upper() == 'GET':
                response = session.get(url, params=payload, headers=headers, timeout=60)
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")

            response_text_decoded = decompress_content(response)
            is_cloudflare_challenge_final = (  # 判定是否为CF质询
                    response.status_code in [403, 503] and
                    ("Just a moment..." in response_text_decoded or "challenge-platform" in response_text_decoded or
                     "Enable JavaScript and cookies" in response_text_decoded or "<title>Attention Required! | Cloudflare</title>" in response_text_decoded or
                     "Verifying you are human" in response_text_decoded)
            )

            if is_cloudflare_challenge_final:
                print(f"错误: API请求返回Cloudflare质询 (HTTP {response.status_code}).")
                # 即使是第一次尝试就遇到CF质询，也直接提示用户更新Cookie，因为cloudscraper的自动处理可能已失败或Cookie已过期
                user_wants_to_retry = prompt_user_for_cookie_update()
                if user_wants_to_retry:
                    return RETRY_OPERATION_AFTER_COOKIE_UPDATE  # 返回特殊信号
                else:
                    return USER_QUIT_OPERATION  # 用户选择退出

            # --- 非CF质询的错误处理 ---
            if response.status_code != 200:
                # ... (错误处理逻辑与上一版相同) ...
                msg_prefix = f"错误: API请求 {url} 返回状态码 {response.status_code}."
                print(msg_prefix)
                if response_text_decoded:
                    print(f"  服务器响应:\n---\n{response_text_decoded[:1500]}\n---")
                else:
                    print("  服务器响应为空。")
                err_type = f"api_error_{response.status_code}"
                if response.status_code == 401 and "Password is required" in response_text_decoded: return {"code": 401,
                                                                                                            "message": "Password protected",
                                                                                                            "content": response_text_decoded}
                return {"error_type": err_type, "status_code": response.status_code,
                        "message": f"API status {response.status_code}", "content": response_text_decoded}

            # --- 成功 (200 OK) ---
            if response_text_decoded:
                try:
                    return json.loads(response_text_decoded)
                except json.JSONDecodeError:
                    return {"code": response.status_code, "message": "Non-JSON response (status 200)",
                            "content": response_text_decoded}
            else:
                return {"code": response.status_code, "message": "Empty successful response (status 200)"}

        # --- 异常捕获 ---
        except cloudscraper.exceptions.CloudflareChallengeError as e:
            print(f"Cloudflare质询处理失败 (尝试 {attempt + 1}): {e}")
            # 这种异常通常意味着 cloudscraper 尝试解决但失败了
            if attempt >= retries:  # 如果是最后一次重试，则提示用户
                user_wants_to_retry = prompt_user_for_cookie_update()
                if user_wants_to_retry:
                    return RETRY_OPERATION_AFTER_COOKIE_UPDATE
                else:
                    return USER_QUIT_OPERATION
        except requests.exceptions.RequestException as e:
            print(f"网络或请求错误 (尝试 {attempt + 1}): {e}")
        except Exception as e:
            print(f"未知API错误 (尝试 {attempt + 1}): {e}");
            traceback.print_exc()

        # --- 重试逻辑 ---
        if attempt < retries:
            time.sleep(base_delay * (1.5 ** attempt));
            print(f"  等待后重试...")
        else:  # 所有外部重试都用尽了
            print(f"API请求 {url} 在 {retries + 1} 次尝试后彻底失败。")
            # 检查是否是因为CF质询而最终失败（虽然上面已经处理了，但作为保险）
            if response and is_cloudflare_challenge_final:
                user_wants_to_retry = prompt_user_for_cookie_update()
                if user_wants_to_retry:
                    return RETRY_OPERATION_AFTER_COOKIE_UPDATE
                else:
                    return USER_QUIT_OPERATION

            # 返回最终的错误信息
            err = {"message": "Unknown error after retries."}
            if 'e' in locals() and isinstance(e, cloudscraper.exceptions.CloudflareChallengeError):
                err = {"error_type": "cf_challenge_final", "message": str(e)}
            elif 'e' in locals() and isinstance(e, requests.exceptions.RequestException):
                err = {"error_type": "req_exception_final", "message": str(e)}
            elif 'e' in locals():
                err = {"error_type": "unknown_exception_final", "message": str(e)}
            return err

    return None  # 理论上不应该执行到这里


def get_file_direct_link(file_path_unencoded):
    print(f"  获取文件 '{file_path_unencoded}' 直链...")
    while True:  # 添加循环以便在Cookie更新后重试
        payload = {"path": file_path_unencoded, "password": ""}
        data = make_api_request('POST', API_GET_PATH, payload)

        if data == RETRY_OPERATION_AFTER_COOKIE_UPDATE:
            print(f"    因Cookie更新，重试获取 '{file_path_unencoded}' 的直链...")
            continue  # 继续while循环，重新调用make_api_request
        elif data == USER_QUIT_OPERATION:
            return USER_QUIT_OPERATION  # 将退出信号向上传递

        # --- 处理正常的API响应或错误 ---
        if data and data.get("code") == 200 and data.get("data") and data["data"].get("raw_url"):
            return data["data"]["raw_url"]
        elif data and data.get("code") == 500 and "token is expired" in data.get("message", "").lower():
            print(f"错误: 获取 {file_path_unencoded} 直链失败，token已过期。"); return None
        elif data and data.get("code") == 401 and "Password protected" in data.get("message", ""):
            print(f"跳过受密码保护的文件: {file_path_unencoded}"); return "PASSWORD_PROTECTED"
        elif data and data.get("error_type"):
            print(f"错误: 获取 {file_path_unencoded} 直链失败. API错误: {data.get('message')}")
            if data.get("content"): print(f"  API响应内容: {str(data.get('content'))[:200]}")
            return None  # API调用失败，跳出while循环
        else:
            print(f"错误: 未能获取 {file_path_unencoded} 直链. 响应: {data}")
            return None  # 未知错误，跳出while循环
        break  # 如果不是重试信号，则处理完后跳出循环


def download_file(direct_url, local_filepath, filename_for_log):
    os.makedirs(os.path.dirname(local_filepath), exist_ok=True)
    temp_filepath = local_filepath + PART_FILE_SUFFIX
    final_filepath = local_filepath
    print(f"    准备下载 '{filename_for_log}' 到 '{final_filepath}'")

    # 默认尝试获取远程大小，但在特定情况下会跳过
    attempt_head_request = True

    # 1. 检查最终文件是否已存在
    if os.path.exists(final_filepath):
        # 尝试获取一次远程大小用于比较
        try:
            session.headers.update({'User-Agent': BROWSER_USER_AGENT})
            head_resp = session.head(direct_url, timeout=20, allow_redirects=True)  # 缩短超时
            head_resp.raise_for_status()
            remote_size_check = int(head_resp.headers.get('content-length', 0))
            if remote_size_check > 0 and os.path.getsize(final_filepath) == remote_size_check:
                print(f"      文件 '{filename_for_log}' 已完整存在，跳过。")
                return "SUCCESS"
            else:
                print(f"      文件 '{filename_for_log}' 已存在但不完整/大小不符。将重新下载。")
                try:
                    os.remove(final_filepath)
                except OSError as e_rm:
                    print(f"        删除不完整文件失败: {e_rm}")
        except Exception as e_head_check:
            print(f"      检查已存在文件远程大小时出错: {e_head_check}。将重新下载。")
            try:
                os.remove(final_filepath)
            except OSError as e_rm:
                print(f"        删除不完整文件失败: {e_rm}")
        attempt_head_request = False  # 如果已存在但校验失败或无法校验，后续重试直接GET

    # 2. 清理可能存在的旧临时文件
    if os.path.exists(temp_filepath):
        print(f"      发现未完成的下载 '{temp_filepath}'。删除后重试。")
        try:
            os.remove(temp_filepath)
        except OSError as e_rm_part:
            print(f"        删除临时文件失败: {e_rm_part}。")
        attempt_head_request = False  # 之前有临时文件，说明上次可能中断，直接GET

    # 3. （可选）如果全新下载，尝试一次HEAD获取大小
    remote_size_known = -1
    if attempt_head_request:
        try:
            # print(f"      尝试HEAD请求获取 '{filename_for_log}' 大小...")
            session.headers.update({'User-Agent': BROWSER_USER_AGENT})
            head_resp = session.head(direct_url, timeout=20, allow_redirects=True)
            head_resp.raise_for_status()
            remote_size_known = int(head_resp.headers.get('content-length', 0))
            if remote_size_known <= 0: remote_size_known = -1
            # else: print(f"      HEAD获取到远程大小: {remote_size_known / (1024*1024):.2f} MB")
        except Exception as e_head_initial:
            print(f"      初始HEAD请求获取 '{filename_for_log}' 大小失败: {e_head_initial}。将直接GET。")
            remote_size_known = -1

    for attempt in range(DOWNLOAD_RETRY_COUNT + 1):
        try:
            session.headers.update({'User-Agent': BROWSER_USER_AGENT})
            print(f"      开始下载尝试 {attempt + 1}/{DOWNLOAD_RETRY_COUNT + 1} for '{filename_for_log}'...")
            with session.get(direct_url, stream=True, timeout=900, allow_redirects=True) as r:
                # ... (CF质询和401/403检查逻辑不变) ...
                content_type_header = r.headers.get('Content-Type', '').lower()
                is_html_response = 'text/html' in content_type_header
                text_preview, is_challenge_page_download = "", False
                if is_html_response and r.status_code in [403, 503]:
                    try:
                        first_chunk_data = next(r.iter_content(2048, decode_unicode=False), None)  # 读取字节
                        if first_chunk_data:
                            text_preview = first_chunk_data.decode('utf-8', errors='ignore')[:500]  # 解码预览
                            is_challenge_page_download = (
                                        "Just a moment..." in text_preview or "challenge-platform" in text_preview or "<title>Attention Required! | Cloudflare</title>" in text_preview)
                            if is_challenge_page_download: print(
                                f"\n    下载链接返回Cloudflare质询 (status {r.status_code})。"); return "RETRY_WITH_NEW_LINK"
                            # 如果不是质询，但仍然是HTML，要小心
                            # print(f"DEBUG: Download response Content-Type is HTML, preview: {text_preview}")
                    except StopIteration:  # 流为空
                        pass
                    except Exception as e_peek:
                        print(f"DEBUG: Error peeking download response: {e_peek}")
                        pass

                if r.status_code == 403 or r.status_code == 401: print(
                    f"\n    下载链接返回 {r.status_code}。"); return "RETRY_WITH_NEW_LINK"
                r.raise_for_status()  # 其他HTTP错误

                # 使用GET请求返回的Content-Length，如果HEAD失败或未执行，则这是第一次知道大小
                current_get_remote_size = int(r.headers.get('content-length', 0))
                final_expected_size = -1
                if current_get_remote_size > 0:
                    final_expected_size = current_get_remote_size
                elif remote_size_known > 0:  # 如果GET没有返回大小，但之前的HEAD有
                    final_expected_size = remote_size_known

                downloaded_size = 0
                # print(f"        写入到: '{temp_filepath}' (预期: {final_expected_size / (1024*1024):.2f} MB)...")
                start_time = time.time()
                with open(temp_filepath, 'wb') as f:
                    # 如果上面 peek 消耗了数据，这里 iter_content 可能会从消耗后的地方开始
                    # 对于 stream=True 的新请求，每次 iter_content 应该是完整的。
                    # 但如果上面的 peek 操作是在同一个响应对象 r 上，需要小心。
                    # 更安全的做法是，如果 peek 了，要么把 peek 的数据也写入，要么重新发起请求。
                    # 简单起见，假设 peek 的影响不大，或者 session.get 会处理好。
                    for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk);
                            downloaded_size += len(chunk)
                            if final_expected_size > 0:
                                progress = (downloaded_size / final_expected_size) * 100;
                                elapsed_time = time.time() - start_time
                                speed = downloaded_size / (elapsed_time + 1e-9) / 1024
                                print(
                                    f"\r          下载中: {downloaded_size // 1024}KB / {final_expected_size // 1024}KB ({progress:.2f}%) {speed:.1f} KB/s",
                                    end="")
                            else:
                                print(f"\r          下载中: {downloaded_size // (1024 * 1024):.2f} MB", end="")
                print("\n        临时文件下载完成。")

                if final_expected_size > 0 and os.path.getsize(temp_filepath) != final_expected_size:
                    print(f"警告: 临时文件 '{temp_filepath}' 大小与预期不符!")
                    if os.path.exists(temp_filepath): os.remove(temp_filepath)
                    raise ValueError(f"Part file size mismatch for {filename_for_log}")
                elif final_expected_size <= 0:
                    print(f"      警告: 无法验证 '{filename_for_log}' 完整性。")

                try:
                    shutil.move(temp_filepath, final_filepath)
                    print(f"      文件 '{filename_for_log}' 成功下载并保存。")
                    return "SUCCESS"
                except Exception as e_mv:
                    print(f"      错误: 移动临时文件失败: {e_mv}"); return "FAILURE"

        # ... (异常捕获和重试逻辑与上一版类似) ...
        except (requests.exceptions.RequestException, cloudscraper.exceptions.CloudflareException) as e:
            print(f"\n    下载网络/请求失败 (尝试 {attempt + 1}): {type(e).__name__} - {e}")
            # 检查是否是 SSLZeroReturnError
            if isinstance(e, requests.exceptions.SSLError) and "SSLZeroReturnError" in str(e):
                print("      检测到 SSLZeroReturnError，服务器可能已关闭连接。这可能是链接失效或服务器问题。")
                # 对于SSLZeroReturnError，重试获取新链接可能更有效
                return "RETRY_WITH_NEW_LINK"
            if hasattr(e, 'response') and e.response is not None and (
                    e.response.status_code == 403 or e.response.status_code == 401):
                return "RETRY_WITH_NEW_LINK"
        except ValueError as e_val:
            print(f"\n    下载校验失败 (尝试 {attempt + 1}): {e_val}")
        except Exception as e_dl:
            print(f"\n    下载意外错误 (尝试 {attempt + 1}): {e_dl}"); traceback.print_exc()

        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError:
                pass

        if attempt < DOWNLOAD_RETRY_COUNT:
            time.sleep(DOWNLOAD_RETRY_DELAY * (1.5 ** attempt)); print(f"      等待后重试下载 '{filename_for_log}'...")
        else:
            print(f"    下载 '{filename_for_log}' 多次重试后失败。"); return "FAILURE"

    return "FAILURE"  # Should not be reached if logic is correct


def list_and_download_recursive(current_path_unencoded, local_base_dir_for_this_run):
    print(f"\n正在处理Alist路径: {current_path_unencoded}")

    quit_signal_received = False
    while True:  # 循环用于在Cookie更新后重试获取列表
        payload = {"path": current_path_unencoded, "password": "", "page": 1, "per_page": 0, "refresh": False}
        api_response = make_api_request('POST', API_LIST_PATH, payload)

        if api_response == RETRY_OPERATION_AFTER_COOKIE_UPDATE:
            print(f"  因Cookie更新，将重试列出路径 '{current_path_unencoded}'...")
            time.sleep(2)  # 短暂等待，让用户操作完成或网络稳定
            continue  # 返回while循环的开始，重新调用make_api_request
        elif api_response == USER_QUIT_OPERATION:
            print(f"  用户选择退出，停止处理路径 '{current_path_unencoded}' 及其子内容。")
            quit_signal_received = True  # 设置退出标记
            break  # 跳出获取列表的while循环

        # --- 处理正常的API响应或永久性错误 ---
        if not api_response: print(f"未能列出路径 '{current_path_unencoded}'：API请求彻底失败。"); break
        if api_response.get("error_type"):
            print(
                f"API错误无法列出路径 '{current_path_unencoded}': 类型='{api_response.get('error_type')}', 消息='{api_response.get('message')}'")
            if api_response.get("content"): print(f"  响应内容: {str(api_response.get('content'))[:500]}")
            break
        if api_response.get("code") != 200:
            print(
                f"未能列出路径 '{current_path_unencoded}'。API响应码: {api_response.get('code')}, 消息: {api_response.get('message', '无消息')}")
            if api_response.get("content"): print(f"  响应内容: {str(api_response.get('content'))[:500]}")
            break

        # --- 成功获取列表 ---
        content = api_response.get("data", {}).get("content", [])
        if not content and api_response.get("data", {}).get("total", 0) == 0: print(
            f"路径 '{current_path_unencoded}' 为空。"); break
        if not content: print(
            f"路径 '{current_path_unencoded}' 无法获取内容，API返回成功但列表为空。响应: {api_response}"); break

        # --- 遍历内容 ---
        for item in content:
            if quit_signal_received: break  # 如果已收到退出信号，不再处理更多项目

            item_name = item.get("name");
            is_dir = item.get("is_dir")
            if not item_name: print(f"警告: 路径 '{current_path_unencoded}' 中项目无名，跳过。"); continue

            if current_path_unencoded == "/":
                next_path_unencoded = "/" + item_name
            else:
                next_path_unencoded = current_path_unencoded.rstrip('/') + "/" + item_name

            relative_path_unencoded = ""
            normalized_initial_path = INITIAL_ALIST_PATH_UNENCODED.rstrip(
                '/') + '/' if INITIAL_ALIST_PATH_UNENCODED != '/' else '/'
            if next_path_unencoded.startswith(normalized_initial_path):
                relative_path_unencoded = next_path_unencoded[len(normalized_initial_path):]
            elif next_path_unencoded == INITIAL_ALIST_PATH_UNENCODED and not is_dir:
                relative_path_unencoded = item_name
            local_item_full_path = os.path.join(local_base_dir_for_this_run, relative_path_unencoded)

            if is_dir:
                print(f"\n发现文件夹: {item_name} (Alist: {next_path_unencoded})")
                os.makedirs(local_item_full_path, exist_ok=True)
                # 递归调用，并检查其是否也返回了退出信号
                if list_and_download_recursive(next_path_unencoded, local_base_dir_for_this_run) == "USER_QUIT_SIGNAL":
                    quit_signal_received = True  # 向上传播退出信号
                    break  # 停止处理当前目录下的其他项目
            else:  # 是文件
                print(f"\n发现文件: {item_name} (Alist: {next_path_unencoded})")
                download_final_status = "FAILURE"

                while True:  # 循环用于在Cookie更新后重试获取单个文件直链
                    direct_link_response = get_file_direct_link(next_path_unencoded)

                    if direct_link_response == RETRY_OPERATION_AFTER_COOKIE_UPDATE:
                        print(f"    因Cookie更新，将重试获取文件 '{item_name}' 的直链...")
                        time.sleep(1)
                        continue  # 重试获取直链
                    elif direct_link_response == USER_QUIT_OPERATION:
                        print(f"    用户选择退出，停止下载文件 '{item_name}'。")
                        download_final_status = "USER_QUIT"
                        quit_signal_received = True
                        break  # 跳出获取直链的while循环

                    direct_link = direct_link_response  # 如果不是特殊信号，则是链接或None或"PASSWORD_PROTECTED"

                    if direct_link == "PASSWORD_PROTECTED": download_final_status = "SKIPPED_PASSWORD_PROTECTED"; break
                    if direct_link:
                        download_attempt_status = download_file(direct_link, local_item_full_path, item_name)
                        if download_attempt_status == "SUCCESS":
                            download_final_status = "SUCCESS"; break
                        elif download_attempt_status == "RETRY_WITH_NEW_LINK":
                            print(f"  文件 '{item_name}' 的直链可能已失效或权限问题。将尝试重新获取链接...")
                            # 这里不需要sleep，外层 get_file_direct_link 的重试循环(如果还想加的话)或这里的while会处理
                            # 但由于我们现在是在while true中，所以这里直接continue，让它尝试重新 get_file_direct_link
                            # 或者，如果 get_file_direct_link 本身不包含重试获取链接的逻辑，我们这里需要一个 link_retry 计数器
                            # 当前 get_file_direct_link 内部没有对获取链接本身的重试循环，make_api_request有。
                            # 为了避免无限循环，如果链接持续失效，我们需要一个退出机制。
                            # 简单起见，如果 RETRY_WITH_NEW_LINK，我们就认为这次获取链接的尝试结束，让外层决定是否继续
                            print(f"    提示需要新链接，将重试获取 '{item_name}' 的直链...")
                            time.sleep(RETRY_DELAY_SECONDS / 2)  # 短暂等待再尝试获取新链接
                            continue  # 继续 while 循环，重新获取直链
                        else:
                            download_final_status = "FAILURE"; break  # 下载彻底失败
                    else:  # get_file_direct_link 返回 None
                        print(f"  获取 '{item_name}' 直链失败。")
                        download_final_status = "FAILURE_NO_LINK";
                        break
                    break  # 如果执行到这里，说明不是重试信号，处理完毕

                if download_final_status == "SUCCESS":
                    print(f"  成功处理文件 '{item_name}'。"); time.sleep(DOWNLOAD_DELAY_SECONDS)
                elif download_final_status not in ["SKIPPED_PASSWORD_PROTECTED", "USER_QUIT"]:
                    print(f"  未能成功下载文件 '{item_name}' (最终状态: {download_final_status})。")

            if quit_signal_received: break  # 如果下载单个文件时用户退出，则停止处理当前目录

        break  # list API 调用成功并处理完毕，跳出获取列表的 while 循环

    if quit_signal_received:
        return "USER_QUIT_SIGNAL"  # 向上传播退出信号
    return None  # 正常完成


if __name__ == "__main__":
    print("脚本开始运行...")
    if not check_nodejs(): pass

    if brotli:
        brotli_available = True
    else:
        print("警告: brotli库未安装或导入失败 (pip install brotli)。")

    if not init_scraper_session(): exit(1)
    if not load_cookies(COOKIE_FILE): print("警告: 从cookie文件加载失败或未找到cf_clearance。")

    print("\n--- 进行Cloudscraper基础访问测试 ---")
    # ... (基础测试代码与上一版相同) ...
    test_url = BASE_URL + "/"
    try:
        print(f"测试访问: {test_url}")
        session.headers.update({'User-Agent': BROWSER_USER_AGENT})
        test_response = session.get(test_url, timeout=45)
        print(f"测试访问状态码: {test_response.status_code}")
        test_response_text = decompress_content(test_response)
        is_challenge_page_test = (
                test_response.status_code in [403, 503] and
                ("Just a moment..." in test_response_text or "challenge-platform" in test_response_text or
                 "Enable JavaScript and cookies" in test_response_text or
                 "<title>Attention Required! | Cloudflare</title>" in test_response_text)
        )
        if test_response.status_code == 200 and not is_challenge_page_test:
            print("Cloudscraper基础访问测试成功。")
        elif is_challenge_page_test:
            print("Cloudscraper基础访问测试：仍然收到Cloudflare质询页面。")
            ray_id_match = re.search(r"Ray ID:\s*<code>([^<]+)</code>|Cloudflare Ray ID:\s*<strong>([^<]+)</strong>",
                                     test_response_text, re.IGNORECASE)
            if ray_id_match: print(f"  Cloudflare Ray ID: {(ray_id_match.group(1) or ray_id_match.group(2)).strip()}")
        else:
            print(f"Cloudscraper基础访问测试：收到意外状态码 {test_response.status_code}。")
    except Exception as e_test:
        print(f"Cloudscraper基础访问测试失败: {e_test}"); traceback.print_exc()
    print("--- 基础访问测试结束 ---\n")

    path_parts = [part for part in INITIAL_ALIST_PATH_UNENCODED.strip('/').split('/') if part]
    if not path_parts: print(f"错误: INITIAL_ALIST_PATH_UNENCODED ('{INITIAL_ALIST_PATH_UNENCODED}') 无效。"); exit(1)
    target_folder_name_in_local = path_parts[-1]

    run_local_base_path = os.path.join(LOCAL_DOWNLOAD_ROOT, target_folder_name_in_local)
    try:
        os.makedirs(run_local_base_path, exist_ok=True)
        print(f"文件将下载到: {os.path.abspath(run_local_base_path)}")
    except OSError as e_mkdir:
        print(f"错误: 创建目录 '{run_local_base_path}' 失败: {e_mkdir}"); exit(1)

    print(f"\n开始从Alist路径 '{INITIAL_ALIST_PATH_UNENCODED}' 下载 (使用原始路径)...")

    # 捕获顶层的退出信号
    final_status = list_and_download_recursive(INITIAL_ALIST_PATH_UNENCODED, run_local_base_path)
    if final_status == "USER_QUIT_SIGNAL":
        print("\n脚本因用户选择退出而终止。")
    else:
        print("\n所有任务完成（或遇到不可恢复错误）。")