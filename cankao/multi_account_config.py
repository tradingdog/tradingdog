# Tidal 多账号配置文件
# 支持批量管理多个账号的播放列表

# 账号列表 - 每个账号只需要OAuth验证一次，之后token会自动保存
# 首次运行时，accounts 列表中的 token 字段留空，脚本会引导你逐个登录
ACCOUNTS = [
    {
        "name": "账号1",  # 账号备注名（方便识别）
        "token_type": "",
        "access_token": "",
        "refresh_token": "",
        "expiry_time": "",
    },
    {
        "name": "账号2",
        "token_type": "",
        "access_token": "",
        "refresh_token": "",
        "expiry_time": "",
    },
    # 可以继续添加更多账号...
]

# 要添加的专辑信息（所有账号共用）
ALBUMS_TO_ADD = [
    {
        "artist_name": "Kenara Lith",
        "album_name": "We Loved Like It Would Last",
        "track_count": 10
    },
    {
        "artist_name": "Solvi Roon",
        "album_name": "Vows Beneath the Ember Sky",
        "track_count": 10
    }
]

# 目标播放列表名称（所有账号共用）
TARGET_PLAYLIST_NAME = "test"
TARGET_PLAYLIST_DESCRIPTION = "自动创建的测试播放列表"
