# -*- coding: utf-8 -*-
"""
弹幕处理服务
负责弹幕等级类型识别等功能
"""
import os
import time
from yaml import safe_load
from utils.logger import logger
from config.prompts import DANMU_LEVEL_PROMPT
from dashscope.aigc.generation import AioGeneration
from core.llm_service import LLMLiveService

# 加载配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)


class DanmuService:
    """弹幕处理服务类"""

    @staticmethod
    async def identify_levels(contents: list) -> list:
        """
        批量识别弹幕等级类型

        Args:
            contents: 弹幕内容列表
        Returns:
            识别后的等级类型列表，与输入列表一一对应
        """
        try:
            # 构建批量识别prompt
            content_list_str = "\n".join([f"{i + 1}. {content}" for i, content in enumerate(contents)])
            level_prompt = DANMU_LEVEL_PROMPT.format(contents=content_list_str)

            # 调用LLM进行等级识别
            responses = await AioGeneration.call(
                model=config["llm"]["model_name"],
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的游戏直播弹幕分析助手，负责根据弹幕内容判断问题类型等级。"
                    },
                    {
                        "role": "user",
                        "content": level_prompt
                    }
                ],
                result_format="message",
                stream=False,
                temperature=0.1  # 低温度，确保结果稳定
            )

            # 解析响应
            if hasattr(responses, 'output') and responses.output and hasattr(responses.output,
                                                                             'choices') and responses.output.choices:
                result = responses.output.choices[0].message.content.strip()

                # 解析返回结果，确保每条弹幕都有对应的等级
                lines = result.strip().split('\n')
                levels = []
                valid_levels = ["充值类问题", "下载类问题", "礼物灯牌类", "专业提问类", "游戏相关普通问题",
                                "其它闲聊问题", "关注或点赞类", "进入直播间类"]

                for line in lines:
                    # 提取等级类型
                    level = line.strip()
                    if level in valid_levels:
                        levels.append(level)
                    else:
                        # 如果解析失败，默认返回其它闲聊问题
                        logger.error(f"弹幕类型解析匹配失败: {level}")
                        levels.append("其它闲聊问题")

                assert len(levels) == len(
                    contents), f"识别等级数量与输入内容数量不一致: {len(levels)} != {len(contents)}"

                return levels[:len(contents)]  # 截断到与输入相同长度

            # 默认返回其它闲聊问题列表
            return ["其它闲聊问题"] * len(contents)
        except Exception as e:
            logger.error(f"弹幕等级识别异常: {e}")
            return ["其它闲聊问题"] * len(contents)

    @staticmethod
    def process_danmu_list(danmu_list):
        """
        处理弹幕列表，添加等级信息

        Args:
            danmu_list: 原始弹幕列表
        Returns:
            处理后的弹幕列表，每个弹幕都添加了等级信息
        """
        from main import DanmuItem
        processed_danmu_list = []
        # 收集所有问题类型的弹幕
        question_danmus = [danmu for danmu in danmu_list if danmu.type == "question"]
        non_question_danmus = [danmu for danmu in danmu_list if danmu.type != "question"]

        return question_danmus, non_question_danmus

    @staticmethod
    def map_level_to_standard(level):
        """
        将识别的等级映射到标准等级

        Args:
            level: 识别的等级
        Returns:
            标准等级：mandatory、important、normal
        """
        level_map = {
            "充值类问题": "mandatory",
            "下载类问题": "mandatory",
            "礼物灯牌类": "important",
            "专业提问类": "important",
            "游戏相关普通问题": "normal",
            "其它闲聊问题": "normal",
            "关注或点赞类": "important",
            "进入直播间类": "normal"
        }
        return level_map.get(level, "normal")

    @staticmethod
    def update_danmu_cache(danmu_cache, new_danmus):
        """
        更新弹幕缓存

        Args:
            danmu_cache: 原弹幕缓存
            new_danmus: 新弹幕列表
        Returns:
            更新后的弹幕缓存
        """
        # 先将新弹幕添加到缓存
        danmu_cache.extend(new_danmus)

        # 过滤掉超过30秒的弹幕
        current_time = time.time()
        danmu_cache = [danmu for danmu in danmu_cache if current_time - danmu.timestamp <= 30]

        # 按时间戳从新到旧排序
        danmu_cache.sort(key=lambda x: x.timestamp, reverse=True)

        # 只保留最近15条弹幕
        if len(danmu_cache) > 15:
            danmu_cache = danmu_cache[:15]

        return danmu_cache

    @staticmethod
    def get_max_level(danmu_list):
        """
        获取弹幕列表中的最高等级

        Args:
            danmu_list: 弹幕列表
        Returns:
            最高等级：mandatory、important、normal
        """
        max_level = "normal"
        for danmu in danmu_list:
            if danmu.level == "mandatory":
                max_level = "mandatory"
                break
            elif danmu.level == "important" and max_level != "mandatory":
                max_level = "important"
        return max_level

    @staticmethod
    def check_mandatory_in_progress(llm_service):
        """
        检查是否有必播句正在生成或播放

        Args:
            llm_service: LLMLiveService实例
        Returns:
            bool: 是否有必播句正在生成或播放
        """
        # 调用LLMLiveService的is_mandatory_in_progress方法
        return llm_service.is_mandatory_in_progress()