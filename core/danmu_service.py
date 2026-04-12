# -*- coding: utf-8 -*-
"""
弹幕处理服务
负责弹幕等级类型识别等功能
"""
import re
import asyncio
from datetime import datetime
from yaml import safe_load
from utils.logger import logger
from utils.common import timer
from config.prompts import DANMU_LEVEL_PROMPT
from dashscope.aigc.generation import AioGeneration
from core.models import DanmuItem

# 加载配置
with open("./config/config.yaml", "r", encoding="utf-8") as f:
    config = safe_load(f)


class DanmuService:
    """弹幕处理服务类"""

    @staticmethod
    @timer
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
                valid_levels = ["充值类问题", "下载类问题", "礼物灯牌类", "专业提问类", "游戏相关普通问题", "其它闲聊问题", "关注或点赞类", "进入直播间类"]

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

                logger.info(f"danmu_cache里的question弹幕等级识别完成，识别结果: {levels}")
                return levels # 截断到与输入相同长度

            # 默认返回其它闲聊问题列表
            logger.info(f"danmu_cache里的question弹幕等级识别失败，原始内容: {contents}")
            return ["其它闲聊问题"] * len(contents)
        except Exception as e:
            logger.error(f"danmu_cache里的question弹幕等级识别异常: {e}")
            return ["其它闲聊问题"] * len(contents)

    @staticmethod
    def process_danmu_list(danmu_list):
        """
        拆分弹幕列表，将问题类型的弹幕和非问题类型的弹幕分离出来
        Args:
            danmu_list: 原始弹幕列表
        Returns:
            问题类型的弹幕列表和非问题类型的弹幕列表
        """
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

        # 过滤掉超过_max_seconds秒的弹幕
        logger.info(f"更新弹幕缓存，当前缓存大小：{len(danmu_cache)}")
        _max_seconds = int(config["live"]["danmu_cache"]["max_seconds"])
        current_time = datetime.now()
        danmu_cache = [danmu for danmu in danmu_cache if (current_time - datetime.strptime(danmu.danmu_time, "%Y-%m-%d %H:%M:%S")).total_seconds() <= _max_seconds]
        logger.info(f"更新弹幕缓存，过滤后缓存大小：{len(danmu_cache)}")

        # 按时间从新到旧排序
        danmu_cache.sort(key=lambda x: datetime.strptime(x.danmu_time, "%Y-%m-%d %H:%M:%S"), reverse=True)

        # 只保留最近_max_nums 条弹幕
        _max_nums = int(config["live"]["danmu_cache"]["max_nums"])
        if len(danmu_cache) > _max_nums:
            danmu_cache = danmu_cache[:_max_nums]
        logger.info(f"更新弹幕缓存，最多保留{_max_nums}条弹幕，当前缓存大小：{len(danmu_cache)}")

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
    def check_live_danmu_in_progress(llm_service, tts_service):
        """
        检查是否有上一次live_danmu调用还未执行完

        Args:
            llm_service: LLMLiveService实例
            tts_service: TTSLiveService实例
        Returns:
            list: [bool, bool]
        """
        # 检查LLM是否正在生成live_danmu类型的文本
        is_danmu_llm_generating = llm_service.generation_type == 'live_danmu'

        # 检查TTS互动队列是否有元素
        has_interact_queue_items = (
                not tts_service.mandatory_queue.empty() or
                not tts_service.important_queue.empty() or
                not tts_service.normal_queue.empty()
        )

        # 如果LLM正在生成live_danmu文本，或互动队列有元素，则认为上一次live_danmu还未执行完
        return [is_danmu_llm_generating, has_interact_queue_items]

    @staticmethod
    async def process_and_update_danmu(danmu_list, danmu_cache) -> tuple:
        """
        处理弹幕等级分类和缓存更新
        Args:
            danmu_list: 原始弹幕列表
            danmu_cache: 原弹幕缓存
        Returns:
            updated_danmu_cache: 更新后的弹幕缓存
        """
        logger.info(f"开始处理弹幕等级分类和缓存更新，原始弹幕数量: {len(danmu_list)}")
        processed_danmu_list = []
        question_danmus, non_question_danmus = DanmuService.process_danmu_list(danmu_list)

        if question_danmus:
            # 批量识别问题类型弹幕的等级
            question_contents = [danmu.content for danmu in question_danmus]
            # 调用DanmuService的identify_levels方法
            levels = await DanmuService.identify_levels(question_contents)

            # 为问题类型弹幕添加等级
            for i, _danmu in enumerate(question_danmus):
                level = DanmuService.map_level_to_standard(levels[i])
                processed_danmu = DanmuItem(
                    username=_danmu.username,
                    content=_danmu.content,
                    type=_danmu.type,
                    level=level,
                    danmu_time=_danmu.danmu_time
                )
                processed_danmu_list.append(processed_danmu)

        # 处理非问题类型的弹幕
        for _danmu in non_question_danmus:
            # 非问题类型弹幕的默认等级
            level = "important" if _danmu.type in ["gift", "follow"] else "normal"
            # 创建新的DanmuItem，添加等级和时间戳
            processed_danmu = DanmuItem(
                username=_danmu.username,
                content=_danmu.content,
                type=_danmu.type,
                level=level,
                danmu_time=_danmu.danmu_time
            )
            processed_danmu_list.append(processed_danmu)

        # 更新danmu_cache
        updated_danmu_cache = DanmuService.update_danmu_cache(danmu_cache, processed_danmu_list)
        logger.info(f"更新弹幕缓存后，当前缓存弹幕数量: {len(updated_danmu_cache)}")

        return updated_danmu_cache

    @staticmethod
    def parse_sentence_level(sentence):
        """
        解析句子等级

        Args:
            sentence: 句子内容
        Returns:
            str: 等级
        """
        match = re.match(r'^【([^】]+)】', sentence)
        level = "normal"
        if match:
            tag = match.group(1)
            if "必播" in tag:
                level = "mandatory"
            elif "重要" in tag:
                level = "important"
        else:
            raise ValueError(f"生成的sentence未匹配到起始等级标签：{sentence}")
        return level

    @staticmethod
    async def handle_danmu_queues(max_level, danmu_cache, llm, tts):
        """
        根据弹幕等级处理TTS队列

        Args:
            max_level: 当前缓存弹幕的最高等级
            danmu_cache: 弹幕缓存
            llm: LLMLiveService实例
            tts: TTSLiveService实例
        Returns:
            str: 处理结果
        """
        full_answer = ""
        is_queue_cleared = False

        # 等级配置映射
        level_config = {
            "mandatory": {
                "clear_important": True,
                "clear_normal": True,
                "check_mandatory_queue": False,
                "check_important_queue": False
            },
            "important": {
                "clear_important": True,
                "clear_normal": True,
                "check_mandatory_queue": True,
                "check_important_queue": True
            },
            "normal": {
                "clear_important": False,
                "clear_normal": True,
                "check_mandatory_queue": False,
                "check_important_queue": False
            }
        }

        # 获取当前等级配置
        config_data = level_config.get(max_level, level_config["normal"])
        logger.info(f"当前最高等级max_level={max_level}，开始处理...")

        # 特殊处理重要等级的队列检查
        _interact_Qsize = f"self.mandatory_queue={tts.mandatory_queue.qsize()}，self.important_queue={tts.important_queue.qsize()}，self.normal_queue={tts.normal_queue.qsize()}"
        if max_level == "mandatory":
            logger.info(_interact_Qsize)
        elif max_level == "important":
            if not tts.mandatory_queue.empty():
                logger.info(f"必播句队列不为空，先处理清空以下队列：" + _interact_Qsize)
            elif not tts.important_queue.empty():
                logger.info(f"重要句队列不为空，先取出一个作为过渡句子，然后处理清空以下列：" + _interact_Qsize)
                try:
                    tts.transitional_sentence = tts.important_queue.get_nowait()
                    logger.info(f"从tts.important_queue取出并赋值过渡句子成功: {tts.transitional_sentence}")
                except asyncio.QueueEmpty:
                    pass
        elif max_level == "normal":
            logger.info(_interact_Qsize)
        else:
            raise ValueError(f"不支持的等级: {max_level}")

        # 处理弹幕
        async for sentence in llm.handle_interact(danmu_cache):
            full_answer += sentence
            if config["tts"]["enabled"]:
                # 解析句子等级
                level = DanmuService.parse_sentence_level(sentence)

                if not is_queue_cleared:
                    # 清空队列逻辑
                    if level == "mandatory":
                        await tts.clear_interact_queues(clear_important=True, clear_normal=True)
                    else:
                        await tts.clear_interact_queues(
                            clear_important=config_data["clear_important"],
                            clear_normal=config_data["clear_normal"]
                        )
                    is_queue_cleared = True

                # 添加到相应等级的队列
                tts.add_to_danmu_queue(sentence, level)
            else:
                logger.info(f"互动回复: {sentence}")

        return full_answer