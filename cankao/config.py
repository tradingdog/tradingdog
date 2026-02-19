# Tidal API 配置文件
# 请填写您的 Tidal 登录凭据

# OAuth 凭据（首次登录后保存的凭据）
# 如果没有凭据，请将 USE_SAVED_CREDENTIALS 设为 False，脚本会引导您进行OAuth登录
USE_SAVED_CREDENTIALS = True

# 保存的 OAuth 凭据（首次登录后会自动填充）
TOKEN_TYPE = "Bearer"
ACCESS_TOKEN = "eyJraWQiOiJ2OU1GbFhqWSIsImFsZyI6IkVTMjU2In0.eyJ0eXBlIjoibzJfYWNjZXNzIiwidWlkIjoyMDY5MTM4ODQsInNjb3BlIjoicl91c3Igd19zdWIgd191c3IiLCJnVmVyIjowLCJzVmVyIjowLCJjaWQiOjEzMzE5LCJjYyI6Ik5aIiwiYXQiOiJJTlRFUk5BTCIsImV4cCI6MTc3MTUyMjQ4Miwic2lkIjoiZGQyZDY2MGEtODJmNy00ZjU1LThjMzctZDFmMzRjODg2OTVmIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLnRpZGFsLmNvbS92MSJ9.iIxOuld_ukZXTJJuBwW_00kKy_Z6_Jc4UtWF7UkGKVoIQ9LnQPYSlaEQWrBrG_oRdWb7S2XXVwSdmwjOcBL2RQ"
REFRESH_TOKEN = "eyJraWQiOiJoUzFKYTdVMCIsImFsZyI6IkVTNTEyIn0.eyJ0eXBlIjoibzJfcmVmcmVzaCIsInVpZCI6MjA2OTEzODg0LCJzY29wZSI6InJfdXNyIHdfc3ViIHdfdXNyIiwiY2lkIjoxMzMxOSwic1ZlciI6MCwiZ1ZlciI6MCwiaXNzIjoiaHR0cHM6Ly9hdXRoLnRpZGFsLmNvbS92MSJ9.AEWcqx7REViq84sKULCHZvsYbzJqeZfw6n9MX4IfW83bCduw7mYufMfg-Mo7oUKC0KqMPMY0n_hRpHQFXXZA2-U7AV30HWimKG4-kNf9M0nnq34ildc1DWVVqiKZ_a5bdTp0nnTmgK9xxJx0ofA3Nn7X8V4gG3yhMiaQoKWEODpYECcf"
EXPIRY_TIME = "2026-02-19 17:34:42.493345"

# 要添加的专辑信息
ALBUMS_TO_ADD = [{'artist_name': 'Kenara Lith', 'album_name': 'We Loved Like It Would Last', 'track_count': 10}, {'artist_name': 'Solvi Roon', 'album_name': 'Vows Beneath the Ember Sky', 'track_count': 10}]

# 目标播放列表名称
TARGET_PLAYLIST_NAME = "test"
TARGET_PLAYLIST_DESCRIPTION = "自动创建的测试播放列表"
