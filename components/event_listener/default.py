from __future__ import annotations
import re
import requests
from typing import Optional, Tuple

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.entities.builtin.platform import message as platform_message


class DefaultEventListener(EventListener):

    def __init__(self):
        super().__init__()

        # 注册消息事件处理
        @self.handler(events.PersonMessageReceived)
        @self.handler(events.GroupMessageReceived)
        async def handler(event_context: context.EventContext):
            msg = str(event_context.event.message_chain).strip()

            # 遍历所有支持平台
            for platform in self.link_handlers.values():
                match = self._match_link(msg, platform["patterns"])
                if match:
                    await platform["handler"](event_context, match)
                    return

        # 定义支持的链接
        self.link_handlers = {
            "bilibili": {
                "patterns": [
                    r"www\.bilibili\.com/video/(BV\w+)",
                    r"b23\.tv/(BV\w+)",
                    r"www\.bilibili\.com/video/av(\d+)",
                    r"b23\.tv/(av\d+)"
                ],
                "handler": self.handle_bilibili
            },
            "github": {
                "patterns": [r"github\.com/([^/]+)/([^/?#]+)"],
                "handler": self.handle_github
            },
            "gitee": {
                "patterns": [r"gitee\.com/([^/]+)/([^/?#]+)"],
                "handler": self.handle_gitee
            },
            "youtube": {
                "patterns": [
                    r'www.youtube.com/watch\?v=([\w-]{11})',
                    r'youtu.be/([\w-]{11})',
                    r'youtube.com/shorts/([\w-]{11})'
                ],
                "handler": self.handle_youtube
            }
        }

    # ------------------ 工具方法 ------------------
    def _format_count(self, count: int) -> str:
        """格式化数字为K单位"""
        if count >= 1000:
            if count % 1000 == 0:
                return f"{count//1000}K"
            return f"{count/1000:.1f}K"
        return str(count)

    def _match_link(self, msg: str, patterns: list) -> Optional[re.Match]:
        for pattern in patterns:
            if match := re.search(pattern, msg):
                return match
        return None

    # ------------------ B站处理 ------------------
    async def handle_bilibili(self, event_context: context.EventContext, match: re.Match):
        id_type = "BV" if "BV" in match.group(0) else "av"
        video_id = match.group(1) if id_type == "BV" else match.group(1).lstrip("av")

        api_url = (
            f"https://api.bilibili.com/x/web-interface/view?bvid={video_id}"
            if id_type == "BV"
            else f"https://api.bilibili.com/x/web-interface/view?aid={video_id}"
        )

        try:
            resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
            data = resp.json()
            if data["code"] != 0:
                raise ValueError("Bilibili API error")

            video_data = data['data']
            stat_data = video_data['stat']

            description = video_data.get('desc') or video_data.get('dynamic', '')
            if isinstance(description, str) and len(description) > 0:
                description = f"📝 描述：{description[:97]}..." if len(description) > 100 else f"📝 描述：{description}"
            else:
                description = None

            message_b = [
                f"🎐 标题：{video_data['title']}",
                f"😃 UP主：{video_data['owner']['name']}"
            ]
            if description:
                message_b.append(description.replace("\n", ""))

            message_b.extend([
                f"💖 点赞：{self._format_count(stat_data.get('like', 0))}  ",
                f"🪙 投币：{self._format_count(stat_data.get('coin', 0))}  ",
                f"✨ 收藏：{self._format_count(stat_data.get('favorite', 0))}",
                f"🌐 链接：https://www.bilibili.com/video/av{video_id}"
            ])

            await event_context.reply(
                platform_message.MessageChain([
                    platform_message.Image(url=video_data['pic']),
                    platform_message.Plain(text="\n".join(message_b))
                ])
            )

        except Exception as e:
            await event_context.reply(
                platform_message.MessageChain([
                    platform_message.Plain(text="视频解析失败")
                ])
            )

    # ------------------ GitHub 处理 ------------------
    async def handle_github(self, event_context: context.EventContext, match: re.Match):
        await self._handle_git_repo(event_context, match.groups(), "GitHub",
            api_template="https://api.github.com/repos/{owner}/{repo}")

    # ------------------ Gitee 处理 ------------------
    async def handle_gitee(self, event_context: context.EventContext, match: re.Match):
        await self._handle_git_repo(event_context, match.groups(), "Gitee",
            api_template="https://gitee.com/api/v5/repos/{owner}/{repo}")

    # ------------------ Git平台通用 ------------------
    async def _handle_git_repo(self, event_context: context.EventContext,
                             groups: Tuple[str],
                             platform: str,
                             api_template: str):
        owner, repo = groups
        try:
            resp = requests.get(
                api_template.format(owner=owner, repo=repo),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            )
            data = resp.json()

            stars = self._format_count(data.get('stargazers_count', 0))
            forks = self._format_count(data.get('forks_count', 0))

            message_git = [
                "━" * 3,
                f"📦 {platform} 仓库：{data['name']}",
                f"📄 描述：{data.get('description', '暂无')}",
                f"⭐ Stars: {stars}",
                f"🍴 Forks: {forks}",
                "━" * 3,
                f"🌐 链接：{data['html_url']}"
            ]

            await event_context.reply(
                platform_message.MessageChain([
                    platform_message.Plain(text="\n".join(message_git))
                ])
            )

        except Exception as e:
            await event_context.reply(
                platform_message.MessageChain([
                    platform_message.Plain(text="仓库信息获取失败")
                ])
            )
    # ------------------ Youtube处理 ------------------
    async def handle_youtube(self, event_context: context.EventContext, match: re.Match):
        video_id = match.group(1)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.163 Safari/537.36'
        }
        key = self.plugin.get_config().get("youtube_key", None)
        try:
            response = requests.get(f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={key}&part=snippet", headers=headers)
            data = response.json()
            if data['pageInfo']['totalResults'] != 0:
                snippet = data['items'][0]['snippet']
                title = snippet['title']
                description = snippet['description']
                channelTitle = snippet['channelTitle']
                thumbnails = snippet['thumbnails']
                publishedAt = snippet['publishedAt']
                tagString = ""
                tags = snippet.get("tags")
                if tags:
                    tagString = ", ".join(tags)
                else:
                    tagString = "无"
                thumbnailUrl = thumbnails['maxres']['url'] if thumbnails['maxres'] else thumbnails['high']['url']
                message_youtube = [
                    f"🎐标题：{title}",
                    f"😃频道：{channelTitle}",
                    f"🌐链接：http://youtu.be/{video_id}"

                ]
                await event_context.reply(platform_message.MessageChain([
                    platform_message.Image(url=thumbnailUrl),
                    platform_message.Plain(text="\n".join(message_youtube))
                ]))
            else:
                await event_context.reply(platform_message.MessageChain([
                    platform_message.Plain(text="视频解析失败")
                ]))
        except Exception as e:
            await event_context.reply(platform_message.MessageChain([
                platform_message.Plain(text=f"视频解析失败")
            ]))
