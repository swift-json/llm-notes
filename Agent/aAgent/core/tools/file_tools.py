"""本地文件操作类工具，所有路径限制在指定工作区内。"""
import os
import shutil

from .registry import Tool, ToolRegistry

TEXT_EXT = {
    ".txt", ".py", ".json", ".md", ".ini", ".csv", ".js", ".ts", ".log",
    ".xml", ".yaml", ".yml", ".html", ".css", ".java", ".c", ".cpp", ".h",
    ".sh", ".bat",
}


def register_file_tools(registry: ToolRegistry, root: str) -> None:
    workspace = os.path.abspath(root)

    def safe(path: str) -> str:
        """把相对路径拼到工作区下，并校验不越界。"""
        resolved = os.path.abspath(os.path.join(workspace, path or "."))
        if resolved != workspace and not resolved.startswith(workspace + os.sep):
            raise PermissionError(f"路径越界: {path}")
        return resolved

    def is_text(resolved: str) -> bool:
        return os.path.splitext(resolved)[1].lower() in TEXT_EXT

    def get_cwd(args: dict) -> str:
        return workspace

    def list_dir(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        if not os.path.isdir(resolved):
            return f"错误: {path} 不是目录"
        lines = [
            f"{name}/" if os.path.isdir(os.path.join(resolved, name)) else name
            for name in sorted(os.listdir(resolved))
        ]
        return "\n".join(lines) if lines else "(空目录)"

    def get_file_type(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        if not os.path.exists(resolved):
            return f"错误: {path} 不存在"
        ext = os.path.splitext(resolved)[1].lower()
        return f"{path} 的类型是: {ext if ext else '(无扩展名)'}"

    def read_file(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        if not os.path.isfile(resolved):
            return f"错误: {path} 不是文件"
        if not is_text(resolved):
            return f"错误: {os.path.splitext(resolved)[1]} 不是纯文本格式，不支持读取"
        with open(resolved, encoding="utf-8", errors="replace") as file:
            content = file.read()
        return content if content else "(空文件)"

    def create_file(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as file:
            file.write(args.get("content", ""))
        return f"已创建文件 {path}"

    def edit_file(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        if not os.path.isfile(resolved):
            return f"错误: {path} 不存在"
        if not is_text(resolved):
            return f"错误: {os.path.splitext(resolved)[1]} 不是纯文本格式，不支持编辑"
        with open(resolved, "w", encoding="utf-8") as file:
            file.write(args["content"])
        return f"已更新文件 {path}"

    def create_dir(args: dict) -> str:
        path = args["path"]
        os.makedirs(safe(path), exist_ok=True)
        return f"已创建目录 {path}"

    def remove_dir(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        if not os.path.isdir(resolved):
            return f"错误: {path} 不是目录"
        shutil.rmtree(resolved)
        return f"已删除目录 {path}"

    def remove_file(args: dict) -> str:
        path = args["path"]
        resolved = safe(path)
        if not os.path.isfile(resolved):
            return f"错误: {path} 不是文件"
        os.remove(resolved)
        return f"已删除文件 {path}"

    def rename_path(args: dict) -> str:
        old_path, new_path = args["old_path"], args["new_path"]
        old, new = safe(old_path), safe(new_path)
        if not os.path.exists(old):
            return f"错误: {old_path} 不存在"
        os.rename(old, new)
        return f"已将 {old_path} 重命名为 {new_path}"

    def path_params(description: str = "路径") -> dict:
        return {"type": "object", "properties": {"path": {"type": "string", "description": description}},
                "required": ["path"]}

    registry.add(Tool("getCwd", "获取当前工作目录的绝对路径", get_cwd))
    registry.add(Tool("listDir", "列出指定目录下所有文件和子目录", list_dir,
                      path_params("目录路径，可传空或 . 表示当前目录")))
    registry.add(Tool("getFileType", "获取指定文件的文件类型（扩展名）", get_file_type,
                      path_params("文件路径")))
    registry.add(Tool("readFile", "获取指定文件的内容，仅支持纯文本格式文件", read_file,
                      path_params("文件路径")))
    registry.add(Tool(
        "createFile",
        "根据指定的目录和文件名创建新的纯文本文件，可附带初始内容",
        create_file,
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件完整路径，如 docs/readme.txt"},
                "content": {"type": "string", "description": "初始内容，可省略"},
            },
            "required": ["path"],
        },
    ))
    registry.add(Tool(
        "editFile",
        "覆盖写入指定文件的全部内容，仅支持纯文本格式文件",
        edit_file,
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "新的完整内容"},
            },
            "required": ["path", "content"],
        },
    ))
    registry.add(Tool("createDir", "创建新目录（自动创建父目录）", create_dir,
                      path_params("目录路径")))
    registry.add(Tool("removeDir", "删除目录及其下所有内容（非空目录也可删除），谨慎使用", remove_dir,
                      path_params("目录路径")))
    registry.add(Tool("removeFile", "删除指定文件", remove_file, path_params("文件路径")))
    registry.add(Tool(
        "renamePath",
        "重命名文件或目录",
        rename_path,
        {
            "type": "object",
            "properties": {
                "old_path": {"type": "string", "description": "原路径"},
                "new_path": {"type": "string", "description": "新路径"},
            },
            "required": ["old_path", "new_path"],
        },
    ))
