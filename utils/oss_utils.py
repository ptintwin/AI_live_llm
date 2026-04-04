# -*- coding: utf-8 -*-
"""
阿里云OSS工具类
"""
import os
import boto3
from botocore.exceptions import NoCredentialsError
from boto3.s3.transfer import TransferConfig
from utils.logger import logger
from yaml import safe_load

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = safe_load(f)


def upload_to_oss(local_file, upload_file_name):
    """
    上传文件到阿里云OSS

    Args:
        local_file: 本地文件路径
        upload_file_name: 上传到OSS的文件名
    Returns:
        str: 上传后的OSS文件URL
    """
    # 从配置文件获取阿里云OSS配置
    oss_config = config.get("oss", {})
    oss_endpoint = oss_config.get("endpoint", "https://oss-cn-beijing.aliyuncs.com")
    oss_bucket = oss_config.get("bucket", "lucastao")

    # 从环境变量获取阿里云OSS凭证
    access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")

    if not access_key_id or not access_key_secret:
        raise ValueError("OSS_ACCESS_KEY_ID和OSS_ACCESS_KEY_SECRET环境变量未设置")
    print(f"access_key_id : {access_key_id}, access_key_secret : {access_key_secret}")

    # 对于阿里云OSS，使用虚拟主机风格访问
    # 确保endpoint不包含bucket名称
    base_endpoint = oss_endpoint
    if oss_bucket in base_endpoint:
        base_endpoint = base_endpoint.replace(f"{oss_bucket}.", "")

    s3 = boto3.client(
        's3',
        endpoint_url=base_endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=access_key_secret,
        config=boto3.session.Config(
            signature_version='s3v4',
            s3={'addressing_style': 'virtual'}
        )
    )

    try:
        # 上传文件
        _config = TransferConfig(multipart_threshold=5 * 1024 * 1024)

        s3.upload_file(
            local_file,
            oss_bucket,
            upload_file_name,
            ExtraArgs={'ACL': 'public-read'},
            Config=_config  # 使用我们自定义的配置
        )

        # 生成URL - 使用虚拟主机风格
        # 从endpoint中提取基础域名
        if "oss-cn-" in base_endpoint:
            # 处理 https://oss-cn-beijing.aliyuncs.com 格式
            domain = base_endpoint.replace("https://", "")
            url = f"https://{oss_bucket}.{domain}/{upload_file_name}"
        elif "oss." in base_endpoint:
            # 处理 https://cn-beijing.oss.aliyuncs.com 格式
            domain = base_endpoint.replace("https://", "")
            url = f"https://{oss_bucket}.{domain}/{upload_file_name}"
        else:
            # 默认格式
            domain = base_endpoint.replace("https://", "")
            url = f"https://{oss_bucket}.{domain}/{upload_file_name}"
        logger.info(f"文件已成功上传到OSS: {url}")
        return url
    except NoCredentialsError:
        raise Exception("阿里云OSS凭证错误")
    except Exception as e:
        raise Exception(f"上传到OSS失败: {e}")


if __name__ == "__main__":
    local_file = "https://lucastao.lucastao.oss-cn-beijing.aliyuncs.com/tts_output_20260404_143402_7c97056b-ff6a-4126-a745-7369f1023851.wav"
    upload_file_name = "tts_output_20260404_143402_7c97056b-ff6a-4126-a745-7369f1023851.wav"
    upload_to_oss(local_file, upload_file_name)