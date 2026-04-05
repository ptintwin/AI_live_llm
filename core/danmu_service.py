# -*- coding: utf-8 -*-
"""
弹幕处理服务
负责弹幕等级类型识别等功能
"""
import os
from yaml import safe_load
from utils.logger import logger
from config.prompts import DANMU_LEVEL_PROMPT
from dashscope.aigc.generation import AioGeneration

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
                valid_levels = ["充值类问题", "专业提问类", "下载类问题", "游戏相关普通问题", "其它闲聊问题"]

                for line in lines:
                    # 提取等级类型
                    level = line.strip()
                    if level in valid_levels:
                        levels.append(level)
                    else:
                        # 如果解析失败，默认返回其它闲聊问题
                        logger.error(f"弹幕类型解析匹配失败: {level}")
                        levels.append("其它闲聊问题")

                assert len(levels) == len(contents), f"识别等级数量与输入内容数量不一致: {len(levels)} != {len(contents)}"

                return levels[:len(contents)]  # 截断到与输入相同长度

            # 默认返回其它闲聊问题列表
            return ["其它闲聊问题"] * len(contents)
        except Exception as e:
            logger.error(f"弹幕等级识别异常: {e}")
            return ["其它闲聊问题"] * len(contents)