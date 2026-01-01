"""
轮询处理器
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage import storage

logger = logging.getLogger(__name__)
router = APIRouter()


class PollResponse(BaseModel):
    """轮询响应"""
    session_id: str
    status: str  # waiting, replied, timeout, error
    has_reply: bool
    replies: list[dict] = []
    message: str = ""


@router.get("/poll/{session_id}", response_model=PollResponse)
async def poll_replies(session_id: str):
    """
    轮询获取会话的回复
    """
    session = await storage.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    
    has_reply = session.status == "replied" and len(session.replies) > 0
    
    return PollResponse(
        session_id=session.session_id,
        status=session.status,
        has_reply=has_reply,
        replies=session.replies,
        message=f"会话状态: {session.status}"
    )


@router.post("/session/{session_id}/timeout")
async def mark_session_timeout(session_id: str):
    """
    标记会话超时
    """
    success = await storage.mark_timeout(session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    return {"success": True, "message": "会话已标记为超时"}
