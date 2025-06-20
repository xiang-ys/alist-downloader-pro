# 高级Alist网盘同步下载器 (支持Cloudflare防护)

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/) [![项目状态](https://img.shields.io/badge/状态-可能维护-green.svg)](https://github.com/xiang-ys/alist-downloader-pro) [![许可证](https://img.shields.io/badge/许可证-MIT-brightgreen.svg)](./LICENSE)

这是一款专为攻克受 **Cloudflare** 高强度安全策略保护的 **Alist** 网站而设计的自动化同步与下载工具。它能够递归地遍历远程目录，并将完整的目录结构和文件稳定、高效地下载到您的本地硬盘。

本项目的核心在于**一套独创的“自动化与人工干预”相结合的Cloudflare绕过策略**，以及一个**企业级的下载内核**。这套体系旨在确保在极端网络环境和长时间下载任务中，实现最高级别的**数据完整性**与**任务可完成性**。

---

## 核心亮点 (Key Features)

-   **🛡️ 顶级的反反爬虫能力 (Cloudflare Bypass)**
    -   **自动化JS质询处理**：深度集成并配置了业界知名的`Cloudscraper`库，能够模拟真实浏览器环境，以应对Cloudflare的JavaScript质询和浏览器指纹验证。
    -   **独创的人机协作(Human-in-the-loop)模式**：当自动化工具遭遇无法解决的强力质询时，系统能智能识别并**自动暂停**。此时，它会通过清晰的命令行指令，引导用户手动更新`cookie.txt`文件，从而实现**任务的无缝恢复**。这一设计从根本上保证了**100%的任务可完成性**。

-   **⚙️ 企业级的下载与同步引擎**
    -   **递归目录同步**：通过高效的深度优先递归算法，能够将Alist上无限层级的目录结构完整地克隆到本地。
    -   **原子化文件操作**：所有文件首先被下载到`.part`临时文件，只有在下载完全成功后，才会重命名为正式文件。这种机制能有效防止因网络中断或程序崩溃而产生的不完整文件，确保本地文件的**原子性**和**完整性**。
    -   **文件完整性校验**：在下载前，通过`HEAD`请求预先检查文件大小，并与本地已存在的文件进行对比，从而智能地实现**增量下载**和**对损坏文件的自动修复**。

-   **🔄 优雅的架构与容错设计**
    -   **多级智能重试**：设计了精细化的多层重试逻辑。它能根据HTTP错误码（如`401/403`）和特定的网络错误（如`SSLZeroReturnError`），智能地判断是应该简单重试，还是需要**重新获取动态生成的下载链接**。
    -   **清晰的状态信号机制**：在复杂的递归调用中，使用了唯一的Python对象作为**跨层级的状态信号**（例如`RETRY_OPERATION_AFTER_COOKIE_UPDATE`）。这种方式避免了使用“魔法字符串”的弊端，使得程序状态的传递清晰、健壮且易于维护。

## 技术栈 (Technology Stack)

-   **核心语言**: Python 3
-   **Cloudflare绕过**: `Cloudscraper`
-   **HTTP请求**: `requests`
-   **数据解压缩**: `brotli`, `gzip`, `zlib`
-   **外部依赖**: 需要`Node.js`环境以支持`Cloudscraper`的JavaScript引擎。

## 安装与配置 (Installation & Setup)

1.  **克隆仓库到本地**
    ```bash
    git clone https://github.com/xiang-ys/alist-downloader-pro.git
    cd alist-downloader-pro
    ```

2.  **安装Node.js**
    本项目依赖的`cloudscraper`库需要一个JavaScript运行时环境。请确保您的系统中已经安装了[Node.js](https://nodejs.org/) (推荐LTS版本)。

3.  **创建并激活Python虚拟环境 (强烈推荐)**
    ```bash
    # Windows
    python -m venv venv
    .\venv\Scripts\activate

    # macOS / Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

4.  **安装Python依赖项**
    ```bash
    pip install -r requirements.txt
    ```

5.  **配置Cookie (关键步骤!)**
    -   在您的浏览器中（推荐使用Chrome），安装一个Cookie管理插件，例如 **Cookie-Editor**。
    -   打开您想要下载的Alist网站，**手动通过所有Cloudflare的人机验证，直到您可以正常浏览网站内容**。
    -   **立即**点击Cookie-Editor插件图标，选择 "导出" -> "Export as Netscape" (或 "Export as Text")。
    -   将导出的内容粘贴到一个名为 `cookie.txt` 的文本文件中，并**确保此文件与Python脚本在同一目录下**。

## 如何使用 (Usage)

1.  **修改脚本配置**: 打开主Python脚本 (`main.py` 或您命名的主文件)，根据您的需求修改顶部的配置项：
    ```python
    # --- 配置区 ---
    BASE_URL = "https://acgdb.de"  # 目标Alist网站的URL
    INITIAL_ALIST_PATH_UNENCODED = "/path/to/remote/folder" # 您想下载的远程起始路径
    LOCAL_DOWNLOAD_ROOT = "F:\\Downloads\\MyAlistFiles" # 本地保存的根目录
    COOKIE_FILE = "cookie.txt" # Cookie文件名
    # ... 其他下载参数可按需调整
    ```

2.  **运行脚本**
    ```bash
    python acgdb.py
    ```
    脚本将开始递归遍历和下载。如果遇到Cloudflare的强力质询，它将会暂停并指导您进行后续操作。

---

## 许可证 (License)

本项目采用 [MIT 许可证](./LICENSE)授权。

## 免责声明 (Disclaimer)

本项目仅用于个人学习和技术研究，旨在探索高级网络爬虫技术、健壮的系统设计以及应对复杂网络环境的策略。**请勿将此项目用于任何商业用途或非法行为。**

使用者应自觉遵守目标网站的用户协议。对于因使用不当而造成的任何后果，项目作者概不负责。
