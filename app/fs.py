from flask import Blueprint, request, jsonify, send_file, render_template_string, abort, Response
from pathlib import Path
import shutil
import mimetypes
from flask import session

MAIN_FILES_DIR = Path("./").resolve()
TEXT_EXTS = {
    ".txt",".py",".js",".html",".css",".json",".md",".yml",".yaml", ".log",
    ".xml",".ini",".cfg",".java",".c",".cpp",".cs",".php",".sh",".bat",".properties"
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}
PDF_EXTS   = {".pdf"}

def register_file_manager(app, get_root, permission_check, url_prefix="/files"):

    bp = Blueprint("files", __name__, url_prefix=url_prefix)

    # ---------------- SAFE PATH ----------------
    def safe(server_id, rel=""):
        if server_id == "main":
            if session.get("role") != "owner":
                abort(403)

            root = MAIN_FILES_DIR
        else:
            permission_check(server_id)
            root = Path(get_root(server_id)).resolve()

        p = (root / rel).resolve()

        if not str(p).startswith(str(root)):
            abort(403)

        return p, root

    # ---------------- HTML ----------------
    HTML = """
 <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cloud Explorer</title>
    <script src="https://code.iconify.design/iconify-icon/3.0.0/iconify-icon.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs/loader.min.js"></script>
    <style>
        :root {
            --bg-darker: #141414;
            --bg-main: #1e1e1e;
            --bg-sidebar: #181818;
            --bg-toolbar: #252526;
            --bg-statusbar: #007acc;
            --bg-hover: #2a2d2e;
            --bg-selected: #37373d;
            --border-color: #3c3c3c;
            --text-main: #cccccc;
            --text-light: #ffffff;
            --text-muted: #858585;
            --accent-color: #0e639c;
            --accent-hover: #1177bb;
            --win11-blur: rgba(30, 30, 30, 0.75);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            user-select: none;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Toolbar */
        .toolbar {
            height: 48px;
            background-color: var(--bg-toolbar);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            padding: 0 12px;
            gap: 8px;
            z-index: 10;
        }

        .toolbar-btn {
            background: transparent;
            border: none;
            color: var(--text-main);
            padding: 6px 10px;
            border-radius: 6px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            transition: background 0.2s, transform 0.1s;
        }

        .toolbar-btn:hover {
            background-color: var(--bg-hover);
            color: var(--text-light);
        }

        .toolbar-btn:active {
            transform: scale(0.97);
        }

        .toolbar-separator {
            width: 1px;
            height: 20px;
            background-color: var(--border-color);
            margin: 0 4px;
        }

        .search-container {
            position: relative;
            margin-left: auto;
            width: 240px;
        }

        .search-input {
            width: 100%;
            background-color: var(--bg-darker);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 6px 10px 6px 32px;
            border-radius: 6px;
            font-size: 13px;
            outline: none;
            transition: border-color 0.2s;
        }

        .search-input:focus {
            border-color: var(--accent-color);
        }

        .search-icon {
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            display: flex;
        }

        /* Breadcrumbs */
        .breadcrumbs-bar {
            height: 34px;
            background-color: var(--bg-main);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            padding: 0 16px;
            font-size: 13px;
            gap: 4px;
            overflow-x: auto;
            white-space: nowrap;
        }

        .breadcrumb-item {
            cursor: pointer;
            color: var(--text-muted);
            padding: 2px 6px;
            border-radius: 4px;
            transition: background 0.2s, color 0.2s;
        }

        .breadcrumb-item:hover {
            background-color: var(--bg-hover);
            color: var(--text-light);
        }

        .breadcrumb-item.active {
            color: var(--text-light);
            font-weight: 500;
        }

        .breadcrumb-separator {
            color: var(--text-muted);
            font-size: 11px;
            display: flex;
            align-items: center;
        }

        /* Layout Workspace */
        .workspace {
            flex: 1;
            display: flex;
            position: relative;
            min-height: 0;
        }

        /* Sidebar Container */
        .sidebar {
            width: 260px;
            min-width: 180px;
            max-width: 600px;
            background-color: var(--bg-sidebar);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            position: relative;
        }

        .sidebar-header {
            padding: 10px 16px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            border-bottom: 1px solid transparent;
        }

        .tree-container {
            flex: 1;
            overflow-y: auto;
            padding: 4px 0;
        }

        /* Tree Items */
        .tree-item {
            display: flex;
            align-items: center;
            padding: 4px 8px 4px 16px;
            cursor: pointer;
            font-size: 13px;
            gap: 6px;
            position: relative;
            white-space: nowrap;
            border-radius: 4px;
            margin: 1px 8px;
            transition: background 0.15s;
        }

        .tree-item:hover {
            background-color: var(--bg-hover);
        }

        .tree-item.selected {
            background-color: var(--bg-selected);
            color: var(--text-light);
        }

        .tree-arrow {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 16px;
            height: 16px;
            color: var(--text-muted);
            transition: transform 0.15s;
        }

        .tree-arrow.expanded {
            transform: rotate(90deg);
        }

        .tree-arrow.hidden {
            visibility: hidden;
        }

        .tree-icon {
            display: flex;
            font-size: 16px;
        }

        /* Resizer */
        .resizer {
            width: 4px;
            background-color: transparent;
            cursor: col-resize;
            transition: background-color 0.3s;
            z-index: 5;
        }

        .resizer:hover, .resizer.dragging {
            background-color: var(--accent-color);
        }

        /* Main View Container */
        .main-viewer {
            flex: 1;
            display: flex;
            flex-direction: column;
            background-color: var(--bg-main);
            position: relative;
            overflow: hidden;
        }

        /* Grid View Mode */
        .grid-container {
            flex: 1;
            padding: 16px;
            overflow-y: auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
            grid-auto-rows: max-content;
            gap: 12px;
            position: relative;
        }

        .grid-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 12px 8px;
            border-radius: 8px;
            cursor: pointer;
            text-align: center;
            border: 1px solid transparent;
            transition: background 0.2s, border-color 0.2s, transform 0.1s;
        }

        .grid-item:hover {
            background-color: var(--bg-hover);
            border-color: var(--border-color);
        }

        .grid-item.selected {
            background-color: var(--bg-selected);
            border-color: var(--accent-color);
        }

        .grid-item:active {
            transform: scale(0.96);
        }

        .grid-icon {
            font-size: 40px;
            margin-bottom: 8px;
            display: flex;
        }

        .grid-name {
            font-size: 13px;
            color: var(--text-main);
            word-break: break-all;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            line-height: 1.3;
        }

        /* Selection Box Tool (Marquee) */
        .selection-box {
            position: absolute;
            border: 1px solid #007acc;
            background-color: rgba(0, 122, 204, 0.2);
            pointer-events: none;
            z-index: 1000;
        }

        /* Content Panel (Editor/Preview) */
        .content-panel {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: var(--bg-main);
            display: flex;
            flex-direction: column;
            z-index: 2000;
            transform: translateY(20px);
            opacity: 0;
            pointer-events: none;
            transition: transform 0.25s cubic-bezier(0.1, 0.9, 0.2, 1), opacity 0.25s;
        }

        .content-panel.active {
            transform: translateY(0);
            opacity: 1;
            pointer-events: auto;
        }

        .panel-header {
            height: 38px;
            background-color: var(--bg-sidebar);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            padding: 0 16px;
            justify-content: space-between;
        }

        .panel-title {
            font-size: 13px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .panel-actions {
            display: flex;
            gap: 6px;
        }

        .panel-body {
            flex: 1;
            position: relative;
            overflow: auto;
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: var(--bg-darker);
        }

        /* Editor Wrapper */
        #monaco-container {
            width: 100%;
            height: 100%;
        }

        /* Previews Layouts */
        .preview-image {
            max-width: 90%;
            max-height: 90%;
            object-fit: contain;
            border-radius: 4px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }

        .preview-video, .preview-audio {
            max-width: 80%;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            border-radius: 8px;
            outline: none;
        }

        .preview-iframe {
            width: 100%;
            height: 100%;
            border: none;
            background: #fff;
        }

        .binary-download-container {
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 16px;
        }

        .btn-primary {
            background-color: var(--accent-color);
            color: var(--text-light);
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            transition: background 0.2s;
        }

        .btn-primary:hover {
            background-color: var(--accent-hover);
        }

        /* Status Bar */
        .status-bar {
            height: 22px;
            background-color: var(--bg-sidebar);
            border-top: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            padding: 0 10px;
            font-size: 12px;
            justify-content: space-between;
            z-index: 10;
        }

        .status-left, .status-right {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .status-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        /* Context Menu */
        .context-menu {
            position: absolute;
            background-color: var(--win11-blur);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 4px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
            display: none;
            flex-direction: column;
            min-width: 160px;
            z-index: 10000;
        }

        .context-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 12px;
            font-size: 13px;
            color: var(--text-main);
            cursor: pointer;
            border-radius: 4px;
            transition: background 0.15s;
        }

        .context-item:hover {
            background-color: rgba(255, 255, 255, 0.1);
            color: var(--text-light);
        }

        .context-item.danger:hover {
            background-color: #a61c1c;
        }

        .context-separator {
            height: 1px;
            background-color: var(--border-color);
            margin: 4px 0;
        }

        /* Modals & Backdrop */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: rgba(0,0,0,0.5);
            backdrop-filter: blur(4px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 30000;
            opacity: 0;
            transition: opacity 0.2s ease-out;
        }

        .modal-overlay.active {
            display: flex;
            opacity: 1;
        }

        .modal-container {
            background-color: var(--bg-toolbar);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            width: 400px;
            max-width: 90%;
            box-shadow: 0 20px 40px rgba(0,0,0,0.6);
            transform: scale(0.9);
            transition: transform 0.2s cubic-bezier(0.1, 0.9, 0.2, 1);
            overflow: hidden;
        }

        .modal-overlay.active .modal-container {
            transform: scale(1);
        }

        .modal-header {
            padding: 16px;
            font-size: 15px;
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-close {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 18px;
            display: flex;
        }

        .modal-close:hover {
            color: var(--text-light);
        }

        .modal-body {
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .modal-input {
            width: 100%;
            background-color: var(--bg-darker);
            border: 1px solid var(--border-color);
            color: var(--text-light);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 14px;
            outline: none;
        }

        .modal-input:focus {
            border-color: var(--accent-color);
        }

        .modal-footer {
            padding: 12px 16px;
            background-color: var(--bg-sidebar);
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }

        .btn-secondary {
            background-color: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
        }

        .btn-secondary:hover {
            background-color: var(--bg-hover);
        }

        /* Upload Progress Area */
        .upload-progress-box {
            position: fixed;
            bottom: 30px;
            right: 20px;
            width: 320px;
            background-color: var(--bg-toolbar);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            display: none;
            flex-direction: column;
            z-index: 40000;
            overflow: hidden;
        }

        .progress-header {
            padding: 10px 12px;
            font-size: 12px;
            font-weight: 600;
            background-color: var(--bg-sidebar);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
        }

        .progress-body {
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .progress-bar-container {
            width: 100%;
            height: 6px;
            background-color: var(--bg-darker);
            border-radius: 3px;
            overflow: hidden;
        }

        .progress-bar-fill {
            width: 0%;
            height: 100%;
            background-color: var(--accent-color);
            transition: width 0.1s linear;
        }

        .progress-text {
            font-size: 11px;
            color: var(--text-muted);
        }

        /* Drag Overlay Indicator */
        .drag-overlay {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(14, 99, 156, 0.2);
            border: 2px dashed var(--accent-color);
            pointer-events: none;
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 100;
        }

        .drag-overlay-msg {
            background-color: var(--bg-toolbar);
            padding: 16px 24px;
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.4);
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 10px;
        }
    </style>
</head>
<body>

    <div class="toolbar">
        <button class="toolbar-btn" onclick="navigateBack()" id="btn-back">
            <iconify-icon icon="vscode-icons:arrow-left"></iconify-icon> Up
        </button>
        <button class="toolbar-btn" onclick="refreshCurrent()">
            <iconify-icon icon="vscode-icons:refresh"></iconify-icon> Refresh
        </button>
        <div class="toolbar-separator"></div>
        <button class="toolbar-btn" onclick="triggerUpload()">
            <iconify-icon icon="vscode-icons:file-type-excel-template"></iconify-icon> Upload Files
        </button>
        <button class="toolbar-btn" onclick="triggerFolderUpload()">
            <iconify-icon icon="vscode-icons:default-folder"></iconify-icon> Upload Folder
        </button>
        <button class="toolbar-btn" onclick="createFolder()">
            <iconify-icon icon="vscode-icons:default-folder-opened"></iconify-icon> New Folder
        </button>
        <button class="toolbar-btn" onclick="pasteItem()" id="btn-paste" style="opacity: 0.5; pointer-events: none;">
            <iconify-icon icon="vscode-icons:file-type-binary"></iconify-icon> Paste
        </button>
        
        <div class="search-container">
            <span class="search-icon"><iconify-icon icon="vscode-icons:file-type-light-js"></iconify-icon></span>
            <input type="text" class="search-input" placeholder="Search explorer..." id="explorer-search" oninput="handleSearch(this.value)">
        </div>
    </div>

    <div class="breadcrumbs-bar" id="breadcrumbs"></div>

    <div class="workspace">
        <div class="sidebar" id="sidebar-panel">
            <div class="sidebar-header">Workspace Files</div>
            <div class="tree-container" id="tree-root"></div>
        </div>

        <div class="resizer" id="sidebar-resizer"></div>

        <div class="main-viewer" id="main-view-zone" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event)">
            
            <div class="grid-container" id="items-grid" onclick="clearSelection(event)"></div>
            
            <div class="drag-overlay" id="drag-zone-visual">
                <div class="drag-overlay-msg">
                    <iconify-icon icon="vscode-icons:default-folder-opened" style="font-size:24px;"></iconify-icon>
                    Drop your contents right here to upload
                </div>
            </div>

            <div class="content-panel" id="viewer-panel">
                <div class="panel-header">
                    <div class="panel-title" id="panel-title-label">
                        <iconify-icon icon="vscode-icons:default-file" id="panel-title-icon"></iconify-icon>
                        <span id="panel-title-text">file.txt</span>
                    </div>
                    <div class="panel-actions">
                        <button class="toolbar-btn" id="panel-save-btn" onclick="saveFile()" style="display:none; background-color: var(--accent-color);">
                            Save (Ctrl+S)
                        </button>
                        <button class="toolbar-btn" onclick="closeViewerPanel()">
                            Close (Esc)
                        </button>
                    </div>
                </div>
                <div class="panel-body" id="panel-content-body">
                    </div>
            </div>

        </div>
    </div>

    <div class="status-bar">
        <div class="status-left">
            <div class="status-item">
                <iconify-icon icon="vscode-icons:default-folder" style="font-size:14px;"></iconify-icon>
                <span id="status-path-label">/</span>
            </div>
        </div>
        <div class="status-right">
            <div class="status-item" id="status-selected-details" style="display:none;">
                <span id="status-selected-count">0 objects selected</span>
            </div>
            <div class="status-item" id="status-file-size-info"></div>
            <div class="status-item" id="status-lang-info"></div>
        </div>
    </div>

    <div class="context-menu" id="app-context-menu">
        <div class="context-item" onclick="menuOpen()">Open</div>
        <div class="context-item" onclick="menuRename()">Rename (F2)</div>
        <div class="context-item" onclick="menuCopy()">Copy (Ctrl+C)</div>
        <div class="context-item" onclick="menuCut()">Cut (Ctrl+X)</div>
        <div class="context-item" onclick="menuDownload()" id="ctx-download-opt">Download</div>
        <div class="context-separator"></div>
        <div class="context-item" onclick="createFolder()">New Folder</div>
        <div class="context-item" onclick="refreshCurrent()">Refresh</div>
        <div class="context-separator"></div>
        <div class="context-item danger" onclick="menuDelete()">Delete (Delete)</div>
    </div>

    <div class="modal-overlay" id="app-modal-layer" onclick="handleModalBackdropClick(event)">
        <div class="modal-container">
            <div class="modal-header">
                <span id="modal-title-text">Prompt dialog box text</span>
                <button class="modal-close" onclick="closeModalWindow()">&times;</button>
            </div>
            <div class="modal-body" id="modal-body-content">
                </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeModalWindow()">Cancel</button>
                <button class="btn-primary" id="modal-submit-action-btn">Confirm action</button>
            </div>
        </div>
    </div>

    <input type="file" id="system-file-picker" multiple style="display:none;" onchange="handleNativeUploadSelection(event, false)">
    <input type="file" id="system-folder-picker" multiple webkitdirectory style="display:none;" onchange="handleNativeUploadSelection(event, true)">

    <div class="upload-progress-box" id="upload-tracking-widget">
        <div class="progress-header">
            <span>Uploading Assets...</span>
            <span id="upload-percentage-val">0%</span>
        </div>
        <div class="progress-body">
            <div class="progress-bar-container">
                <div class="progress-bar-fill" id="upload-progress-fill-bar"></div>
            </div>
            <div class="progress-text" id="upload-status-description-label">Processing items...</div>
        </div>
    </div>

    <script>
        // Global state and tracking matrices
        let currentPath = "";
        let selectedPaths = []; // Track multi-file arrays selection natively
        let lastClickedPath = null; // Memory baseline tracker anchor for ranges matching shifts
        
        let globalClipboard = null; // Structure: { paths: ["...", "..."], mode: "copy" | "cut" }
        let currentDirectoryItemsCache = [];
        let monacoEditorInstance = null;
        let currentlyOpenTextFilePath = null;
        let isMonacoLoaded = false;

        // Context right click memory reference
        let contextTargetItem = null;

        // Selection Box (Marquee) States Tracking Matrix
        let isDraggingBox = false;
        let boxStart = { x: 0, y: 0 };
        let selectionBoxEl = null;

        // App Server routing path parameter helper
        function server() {
            const pathParts = window.location.pathname.split('/');
            const filesIndex = pathParts.indexOf('files');
            if (filesIndex !== -1 && pathParts[filesIndex + 1]) {
                return pathParts[filesIndex + 1];
            }
            return 'default';
        }

        // Initialize App Hook Environment on DOM Loaded Lifecycle
        window.addEventListener('DOMContentLoaded', () => {
            initResizableSidebar();
            initGlobalKeyboardShortcuts();
            initGlobalClickInterceptors();
            initMarqueeSelectionBoxEngine();
            
            // Trigger core folder content loader lookup
            load("");
            
            // Dynamic initialize Monaco infrastructure frameworks asynchronously
            if (typeof require !== 'undefined') {
                require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs' } });
                require(['vs/editor/editor.main'], function() {
                    isMonacoLoaded = true;
                });
            }
        });

        // HTML sanitization helper
        function escapeHtml(text) {
            if (!text) return '';
            return text.toString()
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        // Mapping file identifiers to icon keys
        function getIconForExtension(name, isDir) {
            if (isDir) {
                return 'vscode-icons:default-folder';
            }
            const ext = name.split('.').pop().toLowerCase();
            const mappings = {
                'py': 'vscode-icons:file-type-python',
                'java': 'vscode-icons:file-type-java',
                'js': 'vscode-icons:file-type-js-official',
                'ts': 'vscode-icons:file-type-typescript-official',
                'c': 'vscode-icons:file-type-c',
                'cpp': 'vscode-icons:file-type-cpp',
                'h': 'vscode-icons:file-type-cpp',
                'cs': 'vscode-icons:file-type-csharp',
                'html': 'vscode-icons:file-type-html',
                'htm': 'vscode-icons:file-type-html',
                'css': 'vscode-icons:file-type-css',
                'xml': 'vscode-icons:file-type-xml',
                'yaml': 'vscode-icons:file-type-yaml',
                'yml': 'vscode-icons:file-type-yaml',
                'json': 'vscode-icons:file-type-json',
                'ini': 'vscode-icons:file-type-ini',
                'md': 'vscode-icons:file-type-markdown',
                'txt': 'vscode-icons:file-type-text',
                'log': 'vscode-icons:file-type-text',
                'jar': 'vscode-icons:file-type-zip',
                'zip': 'vscode-icons:file-type-zip',
                'rar': 'vscode-icons:file-type-zip',
                'png': 'vscode-icons:file-type-image',
                'jpg': 'vscode-icons:file-type-image',
                'jpeg': 'vscode-icons:file-type-image',
                'gif': 'vscode-icons:file-type-image',
                'svg': 'vscode-icons:file-type-image',
                'mp3': 'vscode-icons:file-type-audio',
                'wav': 'vscode-icons:file-type-audio',
                'ogg': 'vscode-icons:file-type-audio',
                'mp4': 'vscode-icons:file-type-video',
                'mov': 'vscode-icons:file-type-video',
                'webm': 'vscode-icons:file-type-video',
                'pdf': 'vscode-icons:file-type-pdf'
            };
            return mappings[ext] || 'vscode-icons:default-file';
        }

        function getMonacoLanguageMode(name) {
            const ext = name.split('.').pop().toLowerCase();
            const languageMap = {
                'py': 'python',
                'js': 'javascript',
                'ts': 'typescript',
                'css': 'css',
                'json': 'json',
                'java': 'java',
                'cpp': 'cpp',
                'c': 'c',
                'h': 'cpp',
                'cs': 'csharp',
                'xml': 'xml',
                'yaml': 'yaml',
                'yml': 'yaml',
                'md': 'markdown',
                'sh': 'shell',
                'bat': 'bat',
                'sql': 'sql'
            };
            return languageMap[ext] || 'plaintext';
        }

        function formatBytesToSize(bytes) {
            if (bytes === undefined || bytes === null || isNaN(bytes)) return '';
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        // Core Load Action API Pipeline Implementation
        async function load(path) {
            currentPath = path;
            selectedPaths = [];
            lastClickedPath = null;
            
            document.getElementById('status-selected-details').style.display = 'none';
            document.getElementById('status-file-size-info').textContent = '';
            document.getElementById('status-lang-info').textContent = '';

            document.getElementById('status-path-label').textContent = "/" + path;
            document.getElementById('btn-back').style.opacity = path === "" ? "0.5" : "1";
            document.getElementById('btn-back').style.pointerEvents = path === "" ? "none" : "auto";

            renderBreadcrumbs(path);

            try {
                const s = server();
                const targetUrl = `/files/${s}/api/list?path=${encodeURIComponent(path)}`;
                const response = await fetch(targetUrl);
                const data = await response.json();

                currentDirectoryItemsCache = data.items || [];
                
                renderGridExplorer(currentDirectoryItemsCache);
                renderLeftTreeExplorer(currentDirectoryItemsCache);
            } catch (error) {
                console.error("Critical error inside core load execution layer:", error);
            }
        }

        function renderBreadcrumbs(path) {
            const container = document.getElementById('breadcrumbs');
            container.innerHTML = "";

            const rootNode = document.createElement('span');
            rootNode.className = "breadcrumb-item" + (path === "" ? " active" : "");
            rootNode.textContent = "Home";
            rootNode.onclick = () => load("");
            container.appendChild(rootNode);

            if (path === "") return;

            const segments = path.split('/');
            let currentBuiltPath = "";

            segments.forEach((seg, index) => {
                if (!seg) return;
                
                const separatorNode = document.createElement('span');
                separatorNode.className = "breadcrumb-separator";
                separatorNode.innerHTML = `<iconify-icon icon="vscode-icons:arrow-left" style="transform: rotate(180deg);"></iconify-icon>`;
                container.appendChild(separatorNode);

                if (index === 0) {
                    currentBuiltPath = seg;
                } else {
                    currentBuiltPath += "/" + seg;
                }

                const nodePathValue = currentBuiltPath;
                const breadcrumbNode = document.createElement('span');
                breadcrumbNode.className = "breadcrumb-item" + (index === segments.length - 1 ? " active" : "");
                breadcrumbNode.textContent = seg;
                breadcrumbNode.onclick = () => load(nodePathValue);
                container.appendChild(breadcrumbNode);
            });
        }

        // Render standard items grid. Modified to integrate single-click activation & multi-select modifiers
        function renderGridExplorer(items) {
            const container = document.getElementById('items-grid');
            container.innerHTML = "";

            if (items.length === 0) {
                const emptyMsg = document.createElement('div');
                emptyMsg.style.gridColumn = "1 / -1";
                emptyMsg.style.textAlign = "center";
                emptyMsg.style.padding = "40px";
                emptyMsg.style.color = "var(--text-muted)";
                emptyMsg.style.fontSize = "14px";
                emptyMsg.textContent = "This directory is empty.";
                container.appendChild(emptyMsg);
                return;
            }

            items.forEach(item => {
                const itemNode = document.createElement('div');
                itemNode.className = "grid-item";
                itemNode.setAttribute('data-path', item.path);
                itemNode.setAttribute('data-dir', item.dir);

                if (selectedPaths.includes(item.path)) {
                    itemNode.classList.add('selected');
                }

                itemNode.addEventListener('contextmenu', (e) => {
                    showMenu(e, item.path, item.dir);
                });

                // Single-click operation layer intercept logic integration mapping system
                itemNode.onclick = (e) => {
                    handleSelectionItemClick(e, item);
                };

                const iconString = getIconForExtension(item.name, item.dir);
                
                itemNode.innerHTML = `
                    <div class="grid-icon">
                        <iconify-icon icon="${iconString}"></iconify-icon>
                    </div>
                    <div class="grid-name">${escapeHtml(item.name)}</div>
                `;

                container.appendChild(itemNode);
            });
        }

        function renderLeftTreeExplorer(items) {
            const treeRoot = document.getElementById('tree-root');
            treeRoot.innerHTML = "";

            const containerRow = document.createElement('div');
            containerRow.style.paddingLeft = "8px";

            items.forEach(item => {
                const nodeRow = document.createElement('div');
                nodeRow.className = "tree-item";
                nodeRow.setAttribute('data-path', item.path);
                if (selectedPaths.includes(item.path)) nodeRow.classList.add('selected');

                const arrowClass = item.dir ? "tree-arrow" : "tree-arrow hidden";
                const arrowIcon = item.dir ? `<iconify-icon icon="vscode-icons:arrow-left" style="transform: rotate(180deg);"></iconify-icon>` : "";
                const fileIconString = getIconForExtension(item.name, item.dir);

                nodeRow.innerHTML = `
                    <div class="${arrowClass}">${arrowIcon}</div>
                    <div class="tree-icon"><iconify-icon icon="${fileIconString}"></iconify-icon></div>
                    <span style="overflow:hidden; text-overflow:ellipsis;">${escapeHtml(item.name)}</span>
                `;

                nodeRow.onclick = (e) => {
                    handleSelectionItemClick(e, item);
                };

                nodeRow.addEventListener('contextmenu', (e) => {
                    showMenu(e, item.path, item.dir);
                });

                containerRow.appendChild(nodeRow);
            });

            treeRoot.appendChild(containerRow);
        }

        // Live filtration search processing logic module
        function handleSearch(query) {
            const filtered = currentDirectoryItemsCache.filter(item => 
                item.name.toLowerCase().includes(query.toLowerCase())
            );
            renderGridExplorer(filtered);
        }

        // Unified click routing engine mapping single clicks to instant executions unless modifiers run active
        function handleSelectionItemClick(e, item) {
            e.stopPropagation();
            const p = item.path;

            if (e.shiftKey && lastClickedPath) {
                // Range processing selection algorithms calculations logic block
                const idx1 = currentDirectoryItemsCache.findIndex(x => x.path === lastClickedPath);
                const idx2 = currentDirectoryItemsCache.findIndex(x => x.path === p);
                if (idx1 !== -1 && idx2 !== -1) {
                    const start = Math.min(idx1, idx2);
                    const end = Math.max(idx1, idx2);
                    
                    if (!e.ctrlKey && !e.metaKey) {
                        selectedPaths = [];
                    }

                    for (let i = start; i <= end; i++) {
                        const targetedPathStr = currentDirectoryItemsCache[i].path;
                        if (!selectedPaths.includes(targetedPathStr)) {
                            selectedPaths.push(targetedPathStr);
                        }
                    }
                    syncSelectionUIVisuals();
                }
            } else if (e.ctrlKey || e.metaKey) {
                // Individual element toggle mapping routine allocation tracking logic matrix
                if (selectedPaths.includes(p)) {
                    selectedPaths = selectedPaths.filter(x => x !== p);
                } else {
                    selectedPaths.push(p);
                    lastClickedPath = p;
                }
                syncSelectionUIVisuals();
            } else {
                // Pure default mode standard absolute operation structure maps direct single-click executions instantly
                selectedPaths = [p];
                lastClickedPath = p;
                syncSelectionUIVisuals();

                if (item.dir) {
                    load(p);
                } else {
                    openFile(p);
                }
            }
            updateStatusSelectionInfo();
        }

        // Keep workspace visual selection parameters updated perfectly across all interactive modules simultaneously
        function syncSelectionUIVisuals() {
            document.querySelectorAll('.grid-item, .tree-item').forEach(el => {
                const pathAttr = el.getAttribute('data-path');
                if (selectedPaths.includes(pathAttr)) {
                    el.classList.add('selected');
                } else {
                    el.classList.remove('selected');
                }
            });
        }

        // Marquee Canvas Workspace Selection Engine Construction Implementation
        function initMarqueeSelectionBoxEngine() {
            const gridContainerElement = document.getElementById('items-grid');

            gridContainerElement.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return; // Only process standard primary click drag operations
                if (e.target.closest('.grid-item')) return; // Do not interrupt explicit singular components interactions

                isDraggingBox = true;
                const rect = gridContainerElement.getBoundingClientRect();
                
                boxStart.x = e.clientX - rect.left + gridContainerElement.scrollLeft;
                boxStart.y = e.clientY - rect.top + gridContainerElement.scrollTop;

                selectionBoxEl = document.createElement('div');
                selectionBoxEl.className = 'selection-box';
                selectionBoxEl.style.left = boxStart.x + 'px';
                selectionBoxEl.style.top = boxStart.y + 'px';
                selectionBoxEl.style.width = '0px';
                selectionBoxEl.style.height = '0px';
                
                gridContainerElement.appendChild(selectionBoxEl);

                if (!e.ctrlKey && !e.shiftKey) {
                    selectedPaths = [];
                    syncSelectionUIVisuals();
                }
                e.preventDefault();
            });

            window.addEventListener('mousemove', (e) => {
                if (!isDraggingBox || !selectionBoxEl) return;

                const rect = gridContainerElement.getBoundingClientRect();
                const currentX = e.clientX - rect.left + gridContainerElement.scrollLeft;
                const currentY = e.clientY - rect.top + gridContainerElement.scrollTop;

                const computedLeft = Math.min(boxStart.x, currentX);
                const computedTop = Math.min(boxStart.y, currentY);
                const computedWidth = Math.abs(boxStart.x - currentX);
                const computedHeight = Math.abs(boxStart.y - currentY);

                selectionBoxEl.style.left = computedLeft + 'px';
                selectionBoxEl.style.top = computedTop + 'px';
                selectionBoxEl.style.width = computedWidth + 'px';
                selectionBoxEl.style.height = computedHeight + 'px';

                const boxBounds = {
                    left: computedLeft,
                    top: computedTop,
                    right: computedLeft + computedWidth,
                    bottom: computedTop + computedHeight
                };

                const gridItemNodes = gridContainerElement.querySelectorAll('.grid-item');
                gridItemNodes.forEach(item => {
                    const itemLeft = item.offsetLeft;
                    const itemTop = item.offsetTop;
                    const itemWidth = item.offsetWidth;
                    const itemHeight = item.offsetHeight;

                    const itemBounds = {
                        left: itemLeft,
                        top: itemTop,
                        right: itemLeft + itemWidth,
                        bottom: itemTop + itemHeight
                    };

                    const hitsInsideBoxArea = !(
                        boxBounds.right < itemBounds.left || 
                        boxBounds.left > itemBounds.right || 
                        boxBounds.bottom < itemBounds.top || 
                        boxBounds.top > itemBounds.bottom
                    );

                    const targetPathAttr = item.getAttribute('data-path');
                    if (hitsInsideBoxArea) {
                        if (!selectedPaths.includes(targetPathAttr)) {
                            selectedPaths.push(targetPathAttr);
                        }
                    } else {
                        if (!e.ctrlKey && !e.shiftKey) {
                            selectedPaths = selectedPaths.filter(x => x !== targetPathAttr);
                        }
                    }
                });

                syncSelectionUIVisuals();
                updateStatusSelectionInfo();
            });

            window.addEventListener('mouseup', () => {
                if (isDraggingBox) {
                    isDraggingBox = false;
                    if (selectionBoxEl && selectionBoxEl.parentNode) {
                        selectionBoxEl.parentNode.removeChild(selectionBoxEl);
                    }
                    selectionBoxEl = null;
                }
            });
        }

        function updateStatusSelectionInfo() {
            const countLabelWidget = document.getElementById('status-selected-details');
            const innerTextContainer = document.getElementById('status-selected-count');
            
            if (selectedPaths.length === 0) {
                countLabelWidget.style.display = 'none';
                document.getElementById('status-file-size-info').textContent = '';
                document.getElementById('status-lang-info').textContent = '';
                return;
            }

            countLabelWidget.style.display = 'flex';
            innerTextContainer.textContent = `${selectedPaths.length} objects selected`;

            if (selectedPaths.length === 1) {
                const singleItemObj = currentDirectoryItemsCache.find(x => x.path === selectedPaths[0]);
                if (singleItemObj && !singleItemObj.dir) {
                    document.getElementById('status-file-size-info').textContent = formatBytesToSize(singleItemObj.size || 0);
                    document.getElementById('status-lang-info').textContent = getMonacoLanguageMode(singleItemObj.name).toUpperCase();
                } else {
                    document.getElementById('status-file-size-info').textContent = '';
                    document.getElementById('status-lang-info').textContent = 'FOLDER';
                }
            } else {
                document.getElementById('status-file-size-info').textContent = '';
                document.getElementById('status-lang-info').textContent = '';
            }
        }

        function clearSelection(e) {
            if (e.target.id === "items-grid" || e.target.classList.contains('grid-container')) {
                selectedPaths = [];
                lastClickedPath = null;
                syncSelectionUIVisuals();
                updateStatusSelectionInfo();
            }
        }

        function navigateBack() {
            if (currentPath === "") return;
            const segments = currentPath.split('/');
            segments.pop();
            const upperPath = segments.join('/');
            load(upperPath);
        }

        // Refresh command hook implementation
        function refreshCurrent() {
            load(currentPath);
        }

        // Open File Delivery Routing Operations Engine Pipeline Channel. Enhanced to render HTML previews.
        async function openFile(path) {
            const filename = path.split('/').pop();
            document.getElementById('panel-title-text').textContent = filename;
            document.getElementById('panel-title-icon').setAttribute('icon', getIconForExtension(filename, false));
            
            const bodyZone = document.getElementById('panel-content-body');
            bodyZone.innerHTML = "";
            document.getElementById('panel-save-btn').style.display = "none";
            currentlyOpenTextFilePath = null;

            document.getElementById('viewer-panel').classList.add('active');

            const ext = filename.split('.').pop().toLowerCase();
            const s = server();

            const isImage = ['png','jpg','jpeg','gif','svg','webp','ico'].includes(ext);
            const isVideo = ['mp4','webm','mov','ogg'].includes(ext);
            const isAudio = ['mp3','wav','ogg'].includes(ext);
            const isPdf = ['pdf'].includes(ext);
            
            // Render target HTML files inside an isolated sandbox iframe layout component view frame structure
            const isHtml = ['html', 'htm'].includes(ext);
            
            const isText = ['txt','log','py','js','ts','css','json','xml','yaml','yml','md','sh','bat','cs','cpp','c','h','java','sql','ini',"log","properties"].includes(ext);

            if (isImage) {
                bodyZone.innerHTML = `<img src="/files/${s}/raw?path=${encodeURIComponent(path)}" class="preview-image" alt="Image File Preview">`;
            } else if (isVideo) {
                bodyZone.innerHTML = `<video src="/files/${s}/raw?path=${encodeURIComponent(path)}" controls class="preview-video"></video>`;
            } else if (isAudio) {
                bodyZone.innerHTML = `<audio src="/files/${s}/raw?path=${encodeURIComponent(path)}" controls class="preview-audio"></audio>`;
            } else if (isPdf || isHtml) {
                bodyZone.innerHTML = `<iframe src="/files/${s}/raw?path=${encodeURIComponent(path)}" class="preview-iframe"></iframe>`;
            } else if (isText) {
                bodyZone.innerHTML = `<div id="monaco-container"></div>`;
                document.getElementById('panel-save-btn').style.display = "block";
                currentlyOpenTextFilePath = path;
                
                try {
                    const res = await fetch(`/files/${s}/api/file?path=${encodeURIComponent(path)}`);
                    const fileData = await res.json();
                    initMonacoEditorInstance(fileData.content || "", getMonacoLanguageMode(filename));
                } catch (err) {
                    bodyZone.innerHTML = `<div style="color:#ff6b6b; padding:20px;">Failed to load text content stream details from remote hosting networks.</div>`;
                }
            } else {
                bodyZone.innerHTML = `
                    <div class="binary-download-container">
                        <iconify-icon icon="vscode-icons:default-file" style="font-size: 64px;"></iconify-icon>
                        <div style="font-size: 14px; color: var(--text-muted);">No inline viewer available for this asset variant type.</div>
                        <button class="btn-primary" onclick="triggerDirectFileDownload('${escapeHtml(path)}')">
                            <iconify-icon icon="vscode-icons:file-type-excel-template"></iconify-icon> Download Raw File
                        </button>
                    </div>
                `;
            }
        }

        function closeViewerPanel() {
            document.getElementById('viewer-panel').classList.remove('active');
            if (monacoEditorInstance) {
                monacoEditorInstance.dispose();
                monacoEditorInstance = null;
            }
            currentlyOpenTextFilePath = null;
        }

        function initMonacoEditorInstance(contentString, modeLanguageId) {
            if (!isMonacoLoaded) {
                setTimeout(() => initMonacoEditorInstance(contentString, modeLanguageId), 200);
                return;
            }

            const targetElement = document.getElementById('monaco-container');
            if (!targetElement) return;

            monacoEditorInstance = monaco.editor.create(targetElement, {
                value: contentString,
                language: modeLanguageId,
                theme: 'vs-dark',
                automaticLayout: true,
                fontSize: 14,
                fontFamily: "'Fira Code', Consolas, 'Courier New', monospace",
                minimap: { enabled: true }
            });
        }

        async function saveFile() {
            if (!currentlyOpenTextFilePath || !monacoEditorInstance) return;
            const content = monacoEditorInstance.getValue();
            const s = server();

            try {
                const response = await fetch(`/files/${s}/api/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        path: currentlyOpenTextFilePath,
                        content: content
                    })
                });

                if (response.ok) {
                    const btn = document.getElementById('panel-save-btn');
                    const origText = btn.textContent;
                    btn.textContent = "Saved Successfully!";
                    btn.style.backgroundColor = "#28a745";
                    setTimeout(() => {
                        btn.textContent = origText;
                        btn.style.backgroundColor = "var(--accent-color)";
                    }, 1500);
                } else {
                    alert("Failed to submit code modifications updates back to hosting server systems.");
                }
            } catch (error) {
                console.error("Critical error saving target file updates modification pipeline streams:", error);
            }
        }

        function editFile() {
            if (monacoEditorInstance) {
                monacoEditorInstance.focus();
            }
        }

        // Custom Right Click Selection Menu Coordinate Evaluator Component
        function showMenu(e, path, isDir) {
            e.preventDefault();
            
            // If right-clicked item is not selected, make it the unique item selection
            if (!selectedPaths.includes(path)) {
                selectedPaths = [path];
                lastClickedPath = path;
                syncSelectionUIVisuals();
                updateStatusSelectionInfo();
            }

            contextTargetItem = { path: path, dir: isDir };
            
            const menu = document.getElementById('app-context-menu');
            menu.style.display = "flex";
            menu.style.left = e.clientX + "px";
            menu.style.top = e.clientY + "px";

            const downloadOpt = document.getElementById('ctx-download-opt');
            downloadOpt.style.display = isDir ? "none" : "flex";
        }

        function initGlobalClickInterceptors() {
            document.addEventListener('click', (e) => {
                const menu = document.getElementById('app-context-menu');
                if (menu) menu.style.display = "none";
            });

            document.addEventListener('contextmenu', (e) => {
                if (!e.target.closest('.grid-item') && !e.target.closest('.tree-item')) {
                    contextTargetItem = { path: currentPath, dir: true };
                    const menu = document.getElementById('app-context-menu');
                    menu.style.display = "flex";
                    menu.style.left = e.clientX + "px";
                    menu.style.top = e.clientY + "px";
                    document.getElementById('ctx-download-opt').style.display = "none";
                    e.preventDefault();
                }
            });
        }

        // Context Menu Forwarding Direct Execution Pipelines
        function menuOpen() {
            if (selectedPaths.length > 0) {
                const primaryPathStr = selectedPaths[0];
                const matchedObj = currentDirectoryItemsCache.find(x => x.path === primaryPathStr);
                if (matchedObj) {
                    if (matchedObj.dir) load(primaryPathStr);
                    else openFile(primaryPathStr);
                }
            }
        }

        function menuRename() {
            if (selectedPaths.length > 0) {
                renameItem(selectedPaths[selectedPaths.length - 1]);
            }
        }

        function menuDelete() {
            if (selectedPaths.length > 0) {
                deleteItem(null);
            }
        }

        function menuCopy() {
            if (selectedPaths.length > 0) {
                copyItem(null);
            }
        }

        function menuCut() {
            if (selectedPaths.length > 0) {
                cutItem(null);
            }
        }

        function menuDownload() {
            if (selectedPaths.length > 0) {
                selectedPaths.forEach(p => {
                    const cachedItem = currentDirectoryItemsCache.find(x => x.path === p);
                    if (cachedItem && !cachedItem.dir) {
                        triggerDirectFileDownload(p);
                    }
                });
            }
        }

        // Multi-Selection Compliant Action Operations Pipelines Layers
        function copyItem(explicitPath) {
            const targets = explicitPath ? [explicitPath] : [...selectedPaths];
            if (targets.length === 0) return;

            globalClipboard = { paths: targets, mode: 'copy' };
            const pasteBtn = document.getElementById('btn-paste');
            pasteBtn.style.opacity = "1";
            pasteBtn.style.pointerEvents = "auto";
        }

        function cutItem(explicitPath) {
            const targets = explicitPath ? [explicitPath] : [...selectedPaths];
            if (targets.length === 0) return;

            globalClipboard = { paths: targets, mode: 'cut' };
            const pasteBtn = document.getElementById('btn-paste');
            pasteBtn.style.opacity = "1";
            pasteBtn.style.pointerEvents = "auto";
        }

        async function pasteItem() {
            if (!globalClipboard || globalClipboard.paths.length === 0) return;
            const s = server();

            const operationsPromises = globalClipboard.paths.map(async (srcPath) => {
                const targetFilename = srcPath.split('/').pop();
                const destinationPath = currentPath === "" ? targetFilename : currentPath + "/" + targetFilename;
                
                return fetch(`/files/${s}/api/paste`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        src: srcPath,
                        dst: destinationPath,
                        mode: globalClipboard.mode
                    })
                });
            });

            try {
                await Promise.all(operationsPromises);
                if (globalClipboard.mode === "cut") {
                    globalClipboard = null;
                    document.getElementById('btn-paste').style.opacity = "0.5";
                    document.getElementById('btn-paste').style.pointerEvents = "none";
                }
                load(currentPath);
            } catch (error) {
                console.error("Critical error processing batch paste operation payload:", error);
            }
        }

        function deleteItem(explicitPath) {
            const targets = explicitPath ? [explicitPath] : [...selectedPaths];
            if (targets.length === 0) return;

            const modalTitleText = targets.length === 1 ? `Delete Asset` : `Delete multiple assets (${targets.length})`;
            const itemDescriptionMarkup = targets.length === 1 ? 
                `Are you sure you want to permanently delete <strong>${escapeHtml(targets[0].split('/').pop())}</strong>?` :
                `Are you sure you want to permanently delete these <strong>${targets.length}</strong> items?`;

            openModalWindow(modalTitleText, `
                <div style="font-size:14px;">${itemDescriptionMarkup}</div>
                <div style="font-size:12px; color:#ff6b6b; margin-top:4px;">This action cannot be undone.</div>
            `, async () => {
                const s = server();
                const operationsPromises = targets.map(async (pathStr) => {
                    return fetch(`/files/${s}/api/delete`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: pathStr })
                    });
                });

                try {
                    await Promise.all(operationsPromises);
                    closeModalWindow();
                    load(currentPath);
                } catch (err) {
                    console.error("Critical layer error deleting structural asset path elements:", err);
                }
            });
        }

        function renameItem(path) {
            const currentName = path.split('/').pop();
            openModalWindow(`Rename Asset`, `
                <label style="font-size:12px; color:var(--text-muted);">Enter new asset target name identifier strings:</label>
                <input type="text" id="rename-input-box-field" class="modal-input" value="${escapeHtml(currentName)}">
            `, async () => {
                const newName = document.getElementById('rename-input-box-field').value.trim();
                if (!newName || newName === currentName) {
                    closeModalWindow();
                    return;
                }
                const s = server();
                try {
                    const response = await fetch(`/files/${s}/api/rename`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            path: path,
                            name: newName
                        })
                    });
                    if (response.ok) {
                        closeModalWindow();
                        load(currentPath);
                    } else {
                        alert("Failed executing asset lookup rename modification operation call.");
                    }
                } catch (err) {
                    console.error("Critical pipeline error editing descriptor identification mappings parameters strings:", err);
                }
            });
            
            setTimeout(() => {
                const input = document.getElementById('rename-input-box-field');
                if(input) {
                    input.focus();
                    input.select();
                }
            }, 100);
        }

        function createFolder() {
            openModalWindow(`Create New Folder`, `
                <label style="font-size:12px; color:var(--text-muted);">Enter folder display identifier naming strings:</label>
                <input type="text" id="folder-create-input-box" class="modal-input" placeholder="New Folder">
            `, async () => {
                const folderName = document.getElementById('folder-create-input-box').value.trim();
                if (!folderName) return;
                
                const s = server();
                try {
                    const response = await fetch(`/files/${s}/api/mkdir`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            parent: currentPath,
                            name: folderName
                        })
                    });
                    if (response.ok) {
                        closeModalWindow();
                        load(currentPath);
                    } else {
                        alert("Error generating new remote storage directory workspace structural component location.");
                    }
                } catch (err) {
                    console.error("Critical error building file infrastructure map folder structure blocks:", err);
                }
            });

            setTimeout(() => {
                const input = document.getElementById('folder-create-input-box');
                if(input) input.focus();
            }, 100);
        }

        function triggerDirectFileDownload(path) {
            const s = server();
            const downloadUrl = `/files/${s}/raw?path=${encodeURIComponent(path)}`;
            
            const hiddenDownloadAnchorElement = document.createElement('a');
            hiddenDownloadAnchorElement.href = downloadUrl;
            hiddenDownloadAnchorElement.download = path.split('/').pop();
            document.body.appendChild(hiddenDownloadAnchorElement);
            hiddenDownloadAnchorElement.click();
            document.body.removeChild(hiddenDownloadAnchorElement);
        }

        function triggerUpload() {
            document.getElementById('system-file-picker').click();
        }

        function triggerFolderUpload() {
            document.getElementById('system-folder-picker').click();
        }

        function handleNativeUploadSelection(event, isDirectoryUploadContext) {
            const inputElementFilesListArrayRef = event.target.files;
            if (inputElementFilesListArrayRef.length === 0) return;
            uploadFiles(inputElementFilesListArrayRef);
        }

        async function uploadFiles(filesList) {
            const s = server();
            const trackingBox = document.getElementById('upload-tracking-widget');
            const trackingFill = document.getElementById('upload-progress-fill-bar');
            const trackingText = document.getElementById('upload-status-description-label');
            const trackingPercent = document.getElementById('upload-percentage-val');

            trackingBox.style.display = "flex";
            trackingFill.style.width = "0%";
            trackingPercent.textContent = "0%";
            trackingText.textContent = `Preparing to upload ${filesList.length} items...`;

            const formDataPayloadWrapper = new FormData();
            formDataPayloadWrapper.append('path', currentPath);

            for (let i = 0; i < filesList.length; i++) {
                formDataPayloadWrapper.append('files[]', filesList[i]);
            }

            try {
                const xhrUploaderAgent = new XMLHttpRequest();
                xhrUploaderAgent.open('POST', `/files/${s}/api/upload`, true);

                xhrUploaderAgent.upload.onprogress = (progressEvent) => {
                    if (progressEvent.lengthComputable) {
                        const totalPercentCalculatedValueValueFloat = Math.round((progressEvent.loaded / progressEvent.total) * 100);
                        trackingFill.style.width = totalPercentCalculatedValueValueFloat + "%";
                        trackingPercent.textContent = totalPercentCalculatedValueValueFloat + "%";
                        trackingText.textContent = `Transferring data streams: ${formatBytesToSize(progressEvent.loaded)} of ${formatBytesToSize(progressEvent.total)}`;
                    }
                };

                xhrUploaderAgent.onload = () => {
                    if (xhrUploaderAgent.status === 200) {
                        trackingText.textContent = "Upload completed successfully processing logs synchronization cycles!";
                        trackingFill.style.backgroundColor = "#28a745";
                        setTimeout(() => {
                            trackingBox.style.display = "none";
                            trackingFill.style.backgroundColor = "var(--accent-color)";
                            load(currentPath);
                        }, 1500);
                    } else {
                        trackingText.textContent = "Upload operation transaction error failures encountered.";
                        trackingFill.style.backgroundColor = "#dc3545";
                        setTimeout(() => { trackingBox.style.display = "none"; }, 4000);
                    }
                };

                xhrUploaderAgent.onerror = () => {
                    trackingText.textContent = "Network disconnection disrupted assets transaction pipelines execution contexts.";
                    trackingFill.style.backgroundColor = "#dc3545";
                    setTimeout(() => { trackingBox.style.display = "none"; }, 4000);
                };

                xhrUploaderAgent.send(formDataPayloadWrapper);
            } catch (error) {
                console.error("Critical storage transaction interface channel error encountered uploading asset data block chunks:", error);
                trackingBox.style.display = "none";
            }
        }

        function handleDragOver(e) {
            e.preventDefault();
            e.stopPropagation();
            document.getElementById('drag-zone-visual').style.display = "flex";
        }

        function handleDragLeave(e) {
            e.preventDefault();
            e.stopPropagation();
            if (e.target.id === "drag-zone-visual" || !e.currentTarget.contains(e.relatedTarget)) {
                document.getElementById('drag-zone-visual').style.display = "none";
            }
        }

        function handleDrop(e) {
            e.preventDefault();
            e.stopPropagation();
            document.getElementById('drag-zone-visual').style.display = "none";

            const droppedItemsDataStreamFilesReferencesList = e.dataTransfer.files;
            if (droppedItemsDataStreamFilesReferencesList.length > 0) {
                uploadFiles(droppedItemsDataStreamFilesReferencesList);
            }
        }

        function openModalWindow(titleText, bodyHtmlContentMarkup, confirmActionCallbackFunctionPointer) {
            document.getElementById('modal-title-text').textContent = titleText;
            document.getElementById('modal-body-content').innerHTML = bodyHtmlContentMarkup;
            
            const submitBtn = document.getElementById('modal-submit-action-btn');
            submitBtn.onclick = confirmActionCallbackFunctionPointer;

            document.getElementById('app-modal-layer').classList.add('active');
        }

        function closeModalWindow() {
            document.getElementById('app-modal-layer').classList.remove('active');
        }

        function handleModalBackdropClick(e) {
            if (e.target.id === "app-modal-layer" || e.target.classList.contains('modal-overlay')) {
                closeModalWindow();
            }
        }

        function initResizableSidebar() {
            const sidebar = document.getElementById('sidebar-panel');
            const resizer = document.getElementById('sidebar-resizer');
            
            let trackingStartXPos = 0;
            let trackingStartWidthValueInt = 0;

            resizer.addEventListener('mousedown', (e) => {
                trackingStartXPos = e.clientX;
                trackingStartWidthValueInt = parseInt(document.defaultView.getComputedStyle(sidebar).width, 10);
                resizer.classList.add('dragging');

                document.addEventListener('mousemove', handleMouseMoveSidebarResizeExecutionFrame);
                document.addEventListener('mouseup', handleMouseUpSidebarResizeTerminationFrame);
                e.preventDefault();
            });

            function handleMouseMoveSidebarResizeExecutionFrame(e) {
                const currentDeltaXDistanceComputedOffset = e.clientX - trackingStartXPos;
                const newlyTargetedSidebarWidthCalculatedConstraint = trackingStartWidthValueInt + currentDeltaXDistanceComputedOffset;
                sidebar.style.width = newlyTargetedSidebarWidthCalculatedConstraint + "px";
            }

            function handleMouseUpSidebarResizeTerminationFrame() {
                resizer.classList.remove('dragging');
                document.removeEventListener('mousemove', handleMouseMoveSidebarResizeExecutionFrame);
                document.removeEventListener('mouseup', handleMouseUpSidebarResizeTerminationFrame);
            }
        }

        function initGlobalKeyboardShortcuts() {
            document.addEventListener('keydown', (e) => {
                if (e.key === "Escape") {
                    closeModalWindow();
                    closeViewerPanel();
                    return;
                }

                if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') {
                    if (e.key === "Enter" && document.activeElement.id === "rename-input-box-field") {
                        document.getElementById('modal-submit-action-btn').click();
                    }
                    if (e.key === "Enter" && document.activeElement.id === "folder-create-input-box") {
                        document.getElementById('modal-submit-action-btn').click();
                    }
                    return;
                }

                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                    e.preventDefault();
                    if (currentlyOpenTextFilePath) {
                        saveFile();
                    }
                }

                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') {
                    if (selectedPaths.length > 0) {
                        copyItem(null);
                    }
                }

                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'x') {
                    if (selectedPaths.length > 0) {
                        cutItem(null);
                    }
                }

                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
                    if (globalClipboard) {
                        pasteItem();
                    }
                }

                if (e.key === "Delete") {
                    if (selectedPaths.length > 0) {
                        deleteItem(null);
                    }
                }

                if (e.key === "F2") {
                    if (selectedPaths.length > 0) {
                        renameItem(selectedPaths[selectedPaths.length - 1]);
                    }
                }

                if (e.key === "Enter") {
                    if (selectedPaths.length === 1) {
                        const targetPath = selectedPaths[0];
                        const cachedObj = currentDirectoryItemsCache.find(x => x.path === targetPath);
                        if (cachedObj) {
                            if (cachedObj.dir) load(targetPath);
                            else openFile(targetPath);
                        }
                    }
                }
            });
        }
    </script>
</body>
</html>
    """

    # ---------------- ROUTES ----------------

    @bp.route("/<server_id>/")
    def index(server_id):
        if server_id == "main":
            if session.get("role") != "owner":
                abort(403)
        else:
            permission_check(server_id)

        return render_template_string(HTML)

    @bp.route("/<server_id>/api/list")
    def list_dir(server_id):
        permission_check(server_id)

        rel = request.args.get("path", "")
        p, root = safe(server_id, rel)

        items = []
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            items.append({
                "name": item.name,
                "dir": item.is_dir(),
                "path": str(item.relative_to(root)).replace("\\", "/")
            })

        return jsonify({"path": rel, "items": items})

    @bp.route("/<server_id>/api/file")
    def file(server_id):
        permission_check(server_id)

        p, _ = safe(server_id, request.args["path"])

        if p.is_file():
            return jsonify({"content": p.read_text(errors="ignore")})

        return jsonify({"content": ""})

    @bp.route("/<server_id>/api/save", methods=["POST"])
    def save(server_id):
        permission_check(server_id)

        data = request.json
        p, _ = safe(server_id, data["path"])

        p.write_text(data["content"], encoding="utf8")
        return {"ok": True}

    @bp.route("/<server_id>/api/upload", methods=["POST"])
    def upload(server_id):
        permission_check(server_id)

        current_dir = request.form.get("path", "")

        files = request.files.getlist("files")

        for f in files:

            rel = f.filename.replace("\\", "/")

            if current_dir:
                rel = f"{current_dir}/{rel}"

            p, _ = safe(server_id, rel)

            p.parent.mkdir(parents=True, exist_ok=True)

            f.save(p)

        return {"ok": True}
    
    @bp.route("/<server_id>/api/mkdir", methods=["POST"])
    def mkdir(server_id):
        permission_check(server_id)

        data = request.json

        p, _ = safe(
            server_id,
            f"{data.get('parent','')}/{data['name']}"
        )

        p.mkdir(parents=True, exist_ok=True)

        return {"ok": True}
    @bp.route("/<server_id>/api/delete", methods=["POST"])
    def delete(server_id):
        permission_check(server_id)

        p, _ = safe(server_id, request.json["path"])

        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()

        return {"ok": True}
    
    @bp.route("/<server_id>/api/rename", methods=["POST"])
    def rename(server_id):
        permission_check(server_id)

        data = request.json

        src, root = safe(server_id, data["path"])

        dst = src.parent / data["name"]

        if not str(dst.resolve()).startswith(str(root)):
            abort(403)

        src.rename(dst)

        return {"ok": True}
    
    @bp.route("/<server_id>/api/paste", methods=["POST"])
    def paste(server_id):
        permission_check(server_id)

        data = request.json

        src, _ = safe(server_id, data["src"])

        name = src.name

        if data["dst"]:
            dst_rel = f"{data['dst']}/{name}"
        else:
            dst_rel = name

        dst, _ = safe(server_id, dst_rel)

        if data["mode"] == "copy":

            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        else:

            shutil.move(str(src), str(dst))

        return {"ok": True}
    @bp.route("/<server_id>/raw")
    def raw(server_id):
        permission_check(server_id)

        path = safe(server_id, request.args["path"])[0]

        # FORCE DOWNLOAD FOR BINARY FILES LIKE .jar
        return send_file(
            path,
            as_attachment=True,
            download_name=path.name
        )

    app.register_blueprint(bp)