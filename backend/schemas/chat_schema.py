from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    user_name: str = "marcos"
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.8, ge=0, le=2)
    top_p: float = Field(default=0.9, ge=0, le=1)
    num_predict: int = Field(default=512, ge=32, le=4096)
    voice_mode: bool = False


class TTSRequest(BaseModel):
    text: str