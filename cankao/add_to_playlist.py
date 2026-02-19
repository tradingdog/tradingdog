#!/usr/bin/env python3
"""
Tidal 播放列表添加脚本
功能：搜索指定艺人的专辑，并将歌曲添加到播放列表
"""

import tidalapi
from datetime import datetime
import config


def save_credentials(session):
    """保存登录凭据到配置文件"""
    credentials = f'''# Tidal API 配置文件
# 请填写您的 Tidal 登录凭据

# OAuth 凭据（首次登录后保存的凭据）
# 如果没有凭据，请将 USE_SAVED_CREDENTIALS 设为 False，脚本会引导您进行OAuth登录
USE_SAVED_CREDENTIALS = True

# 保存的 OAuth 凭据（首次登录后会自动填充）
TOKEN_TYPE = "{session.token_type}"
ACCESS_TOKEN = "{session.access_token}"
REFRESH_TOKEN = "{session.refresh_token}"
EXPIRY_TIME = "{session.expiry_time}"

# 要添加的专辑信息
ALBUMS_TO_ADD = {config.ALBUMS_TO_ADD}

# 目标播放列表名称
TARGET_PLAYLIST_NAME = "{config.TARGET_PLAYLIST_NAME}"
TARGET_PLAYLIST_DESCRIPTION = "{config.TARGET_PLAYLIST_DESCRIPTION}"
'''
    with open('config.py', 'w', encoding='utf-8') as f:
        f.write(credentials)
    print("✓ 登录凭据已保存到 config.py")


def login():
    """登录到 Tidal"""
    session = tidalapi.Session()
    
    if config.USE_SAVED_CREDENTIALS and config.ACCESS_TOKEN:
        print("正在使用保存的凭据登录...")
        try:
            # 解析过期时间
            expiry_time = datetime.fromisoformat(config.EXPIRY_TIME) if config.EXPIRY_TIME else None
            success = session.load_oauth_session(
                config.TOKEN_TYPE,
                config.ACCESS_TOKEN,
                config.REFRESH_TOKEN,
                expiry_time
            )
            if success and session.check_login():
                print(f"✓ 登录成功！用户: {session.user.first_name} {session.user.last_name}")
                return session
            else:
                print("✗ 保存的凭据已过期，需要重新登录")
        except Exception as e:
            print(f"✗ 使用保存的凭据登录失败: {e}")
    
    # OAuth 登录
    print("正在进行 OAuth 登录...")
    print("请在浏览器中打开以下链接并登录:")
    
    login_info, future = session.login_oauth()
    print(f"\n>>> 链接: {login_info.verification_uri_complete}")
    print(f">>> 或者访问 {login_info.verification_uri} 并输入代码: {login_info.user_code}\n")
    
    future.result()  # 等待登录完成
    
    if session.check_login():
        print(f"✓ 登录成功！用户: {session.user.first_name} {session.user.last_name}")
        save_credentials(session)
        return session
    else:
        raise Exception("登录失败")


def search_album(session, artist_name, album_name):
    """搜索指定艺人的专辑"""
    print(f"\n正在搜索: 艺人 '{artist_name}' - 专辑 '{album_name}'")
    
    # 搜索专辑
    search_query = f"{artist_name} {album_name}"
    results = session.search(search_query, models=[tidalapi.album.Album])
    
    # 处理返回结果 - 可能是字典或对象
    albums = None
    if isinstance(results, dict):
        albums = results.get('albums', [])
    elif hasattr(results, 'albums'):
        albums = results.albums
    
    if not albums:
        print(f"✗ 未找到专辑: {album_name}")
        return None
    
    # 查找匹配的专辑
    for album in albums:
        # 检查艺人名是否匹配（忽略大小写）
        album_artists = []
        if hasattr(album, 'artists') and album.artists:
            album_artists = [a.name.lower() for a in album.artists]
        if hasattr(album, 'artist') and album.artist:
            album_artists.append(album.artist.name.lower())
        
        artist_match = artist_name.lower() in album_artists or any(
            artist_name.lower() in a for a in album_artists
        )
        
        album_name_attr = album.name if hasattr(album, 'name') else str(album)
        album_match = album_name.lower() in album_name_attr.lower() if album_name_attr else False
        
        if artist_match and album_match:
            artist_display = album.artist.name if hasattr(album, 'artist') and album.artist else 'Unknown'
            print(f"✓ 找到专辑: {album_name_attr} - {artist_display}")
            return album
    
    # 如果精确匹配失败，返回第一个结果
    first_album = albums[0]
    first_name = first_album.name if hasattr(first_album, 'name') else str(first_album)
    first_artist = first_album.artist.name if hasattr(first_album, 'artist') and first_album.artist else 'Unknown'
    print(f"⚠ 未找到精确匹配，使用最相近结果: {first_name} - {first_artist}")
    return first_album


def get_or_create_playlist(session, playlist_name, description=""):
    """获取或创建播放列表"""
    print(f"\n正在查找播放列表: '{playlist_name}'")
    
    # 获取用户的所有播放列表
    user_playlists = session.user.playlists()
    
    # 查找是否已存在
    for playlist in user_playlists:
        if playlist.name and playlist.name.lower() == playlist_name.lower():
            print(f"✓ 找到已存在的播放列表: {playlist.name}")
            return playlist
    
    # 创建新播放列表
    print(f"正在创建新播放列表: '{playlist_name}'")
    playlist = session.user.create_playlist(playlist_name, description)
    print(f"✓ 播放列表创建成功: {playlist.name}")
    return playlist


def add_tracks_to_playlist(playlist, tracks, max_tracks=10):
    """将歌曲添加到播放列表"""
    if not tracks:
        print("✗ 没有歌曲可添加")
        return
    
    # 限制添加的歌曲数量
    tracks_to_add = tracks[:max_tracks]
    track_ids = [track.id for track in tracks_to_add]
    
    print(f"正在添加 {len(tracks_to_add)} 首歌曲到播放列表...")
    
    try:
        playlist.add(track_ids)
        print(f"✓ 成功添加 {len(tracks_to_add)} 首歌曲:")
        for i, track in enumerate(tracks_to_add, 1):
            artist_name = track.artist.name if track.artist else "Unknown"
            print(f"   {i}. {track.name} - {artist_name}")
    except Exception as e:
        print(f"✗ 添加歌曲失败: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("Tidal 播放列表添加工具")
    print("=" * 60)
    
    # 登录
    session = login()
    
    # 获取或创建播放列表
    playlist = get_or_create_playlist(
        session, 
        config.TARGET_PLAYLIST_NAME,
        config.TARGET_PLAYLIST_DESCRIPTION
    )
    
    # 处理每张专辑
    total_added = 0
    for album_info in config.ALBUMS_TO_ADD:
        artist_name = album_info["artist_name"]
        album_name = album_info["album_name"]
        track_count = album_info.get("track_count", 10)
        
        # 搜索专辑
        album = search_album(session, artist_name, album_name)
        
        if album:
            # 获取专辑的歌曲
            tracks = album.tracks()
            print(f"专辑共有 {len(tracks)} 首歌曲")
            
            # 添加歌曲到播放列表
            add_tracks_to_playlist(playlist, tracks, track_count)
            total_added += min(len(tracks), track_count)
    
    print("\n" + "=" * 60)
    print(f"✓ 完成！共添加 {total_added} 首歌曲到播放列表 '{config.TARGET_PLAYLIST_NAME}'")
    print("=" * 60)


if __name__ == "__main__":
    main()
