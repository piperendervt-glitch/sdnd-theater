"""SNSクライアント抽象レイヤー"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv

load_dotenv()


class SocialClient(ABC):
    @abstractmethod
    def post(self, text: str) -> dict:
        """投稿してpost_idを含む辞書を返す"""
        pass


class XClient(SocialClient):
    """tweepy v2 APIクライアント"""

    def __init__(self):
        import tweepy

        self.client = tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        )

    def post(self, text: str) -> dict:
        response = self.client.create_tweet(text=text)
        return {"post_id": response.data["id"], "platform": "x"}


class BlueSkyClient(SocialClient):
    """将来実装用プレースホルダー"""

    def post(self, text: str) -> dict:
        raise NotImplementedError("Bluesky対応は将来実装予定")


class SocialClientFactory:
    @staticmethod
    def create(platform: str = "x") -> SocialClient:
        if platform == "x":
            return XClient()
        elif platform == "bluesky":
            return BlueSkyClient()
        else:
            raise ValueError(f"Unknown platform: {platform}")
