"""
文件存储模块

用于保存过长的消息内容为 Markdown 文件，并提供公开访问的 URL。
支持定期清理过期文件（默认 7 天）。
"""
import os
import uuid
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileStorage:
    """
    文件存储管理器
    
    功能：
    - 保存消息内容为 .md 文件
    - 生成公开访问的 URL
    - 定期清理过期文件
    """
    
    def __init__(
        self,
        storage_dir: str = "/data/projects/hitl/static/files",
        url_prefix: str = "https://hitl.woa.com/files",
        retention_days: int = 7
    ):
        """
        初始化文件存储
        
        Args:
            storage_dir: 文件存储目录
            url_prefix: 公开访问的 URL 前缀
            retention_days: 文件保留天数
        """
        self.storage_dir = Path(storage_dir)
        self.url_prefix = url_prefix.rstrip("/")
        self.retention_days = retention_days
        
        # 确保目录存在
        self._ensure_directory()
        
        # 清理任务句柄
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def _ensure_directory(self) -> None:
        """确保存储目录存在"""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"文件存储目录: {self.storage_dir}")
        except Exception as e:
            logger.warning(f"创建存储目录失败: {e}，将使用临时目录")
            self.storage_dir = Path("/tmp/hil-files")
            self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def save_message(
        self,
        content: str,
        short_id: str = "",
        project_name: str = ""
    ) -> tuple[str, str]:
        """
        保存消息内容为 Markdown 文件
        
        Args:
            content: 消息内容
            short_id: 会话短 ID（用于文件名）
            project_name: 项目名称（用于文件头）
        
        Returns:
            (filename, url) - 文件名和公开访问 URL
        """
        # 生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        
        if short_id:
            filename = f"{short_id}_{timestamp}_{unique_id}.md"
        else:
            filename = f"msg_{timestamp}_{unique_id}.md"
        
        file_path = self.storage_dir / filename
        
        # 构建文件内容
        file_content = self._build_file_content(content, short_id, project_name)
        
        # 写入文件
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(file_content)
            
            url = f"{self.url_prefix}/{filename}"
            logger.info(f"消息已保存: {filename} ({len(content)} bytes)")
            return filename, url
            
        except Exception as e:
            logger.error(f"保存文件失败: {e}")
            raise
    
    def _build_file_content(
        self,
        content: str,
        short_id: str,
        project_name: str
    ) -> str:
        """构建 Markdown 文件内容"""
        lines = []
        
        # 添加头部信息
        lines.append("---")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if short_id:
            lines.append(f"会话ID: #{short_id}")
        if project_name:
            lines.append(f"项目: {project_name}")
        lines.append(f"过期时间: {(datetime.now() + timedelta(days=self.retention_days)).strftime('%Y-%m-%d')}")
        lines.append("---")
        lines.append("")
        
        # 添加消息内容
        lines.append(content)
        
        return "\n".join(lines)
    
    def delete_file(self, filename: str) -> bool:
        """删除指定文件"""
        file_path = self.storage_dir / filename
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"已删除文件: {filename}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除文件失败: {filename}, {e}")
            return False
    
    def cleanup_expired_files(self) -> int:
        """
        清理过期文件
        
        Returns:
            删除的文件数量
        """
        if not self.storage_dir.exists():
            return 0
        
        cutoff_time = datetime.now() - timedelta(days=self.retention_days)
        deleted_count = 0
        
        try:
            for file_path in self.storage_dir.glob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if mtime < cutoff_time:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug(f"清理过期文件: {file_path.name}")
                except Exception as e:
                    logger.warning(f"无法处理文件 {file_path}: {e}")
            
            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 个过期文件")
            
        except Exception as e:
            logger.error(f"清理过期文件失败: {e}")
        
        return deleted_count
    
    async def start_cleanup_task(self, interval_hours: int = 24) -> None:
        """
        启动定期清理任务
        
        Args:
            interval_hours: 清理间隔（小时）
        """
        if self._cleanup_task and not self._cleanup_task.done():
            logger.warning("清理任务已在运行")
            return
        
        async def cleanup_loop():
            while True:
                try:
                    # 执行清理
                    self.cleanup_expired_files()
                except Exception as e:
                    logger.error(f"定期清理失败: {e}")
                
                # 等待下次执行
                await asyncio.sleep(interval_hours * 3600)
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info(f"文件清理任务已启动，间隔: {interval_hours} 小时")
    
    def stop_cleanup_task(self) -> None:
        """停止定期清理任务"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("文件清理任务已停止")


# 全局实例
_file_storage: Optional[FileStorage] = None


def get_file_storage() -> FileStorage:
    """获取文件存储实例"""
    global _file_storage
    if _file_storage is None:
        # 从环境变量读取配置
        storage_dir = os.getenv("FILE_STORAGE_DIR", "/data/projects/hitl/static/files")
        url_prefix = os.getenv("FILE_URL_PREFIX", "https://hitl.woa.com/files")
        retention_days = int(os.getenv("FILE_RETENTION_DAYS", "7"))
        
        _file_storage = FileStorage(
            storage_dir=storage_dir,
            url_prefix=url_prefix,
            retention_days=retention_days
        )
    
    return _file_storage


def init_file_storage(
    storage_dir: str = "/data/projects/hitl/static/files",
    url_prefix: str = "https://hitl.woa.com/files",
    retention_days: int = 7
) -> FileStorage:
    """
    初始化文件存储（显式配置）
    
    Args:
        storage_dir: 文件存储目录
        url_prefix: 公开访问的 URL 前缀
        retention_days: 文件保留天数
    
    Returns:
        FileStorage 实例
    """
    global _file_storage
    _file_storage = FileStorage(
        storage_dir=storage_dir,
        url_prefix=url_prefix,
        retention_days=retention_days
    )
    return _file_storage
