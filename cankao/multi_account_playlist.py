#!/usr/bin/env python3
"""
Tidal 多账号批量播放列表管理脚本
功能：批量为多个账号添加歌曲到播放列表
特点：每个账号只需OAuth验证一次，token自动保存供后续使用
"""

import tidalapi
from datetime import datetime
import multi_account_config as config


def save_config():
    """保存更新后的配置到文件"""
    accounts_str = "[\n"
    for acc in config.ACCOUNTS:
        accounts_str += f'''    {{
        "name": "{acc['name']}",
        "token_type": "{acc.get('token_type', '')}",
        "access_token": "{acc.get('access_token', '')}",
        "refresh_token": "{acc.get('refresh_token', '')}",
        "expiry_time": "{acc.get('expiry_time', '')}",
    }},
'''
    accounts_str += "]"
    
    content = f'''# Tidal 多账号配置文件
# 支持批量管理多个账号的播放列表

# 账号列表 - 每个账号只需要OAuth验证一次，之后token会自动保存
# 首次运行时，accounts 列表中的 token 字段留空，脚本会引导你逐个登录
ACCOUNTS = {accounts_str}

# 要添加的专辑信息（所有账号共用）
ALBUMS_TO_ADD = {config.ALBUMS_TO_ADD}

# 目标播放列表名称（所有账号共用）
TARGET_PLAYLIST_NAME = "{config.TARGET_PLAYLIST_NAME}"
TARGET_PLAYLIST_DESCRIPTION = "{config.TARGET_PLAYLIST_DESCRIPTION}"
'''
    with open('multi_account_config.py', 'w', encoding='utf-8') as f:
        f.write(content)


def login_account(account, index):
    """登录单个账号"""
    session = tidalapi.Session()
    account_name = account.get('name', f'账号{index+1}')
    
    # 尝试使用保存的token登录
    if account.get('access_token'):
        print(f"  正在使用保存的token登录...")
        try:
            expiry_time = datetime.fromisoformat(account['expiry_time']) if account.get('expiry_time') else None
            success = session.load_oauth_session(
                account.get('token_type', 'Bearer'),
                account['access_token'],
                account.get('refresh_token', ''),
                expiry_time
            )
            if success and session.check_login():
                print(f"  ✓ 自动登录成功！")
                # 更新token（可能已刷新）
                account['token_type'] = session.token_type
                account['access_token'] = session.access_token
                account['refresh_token'] = session.refresh_token
                account['expiry_time'] = str(session.expiry_time)
                return session
            else:
                print(f"  ✗ Token已过期，需要重新验证")
        except Exception as e:
            print(f"  ✗ 自动登录失败: {e}")
    
    # OAuth验证
    print(f"  需要OAuth验证，请在浏览器中完成登录:")
    login_info, future = session.login_oauth()
    print(f"  >>> 链接: {login_info.verification_uri_complete}")
    print(f"  >>> 或访问 {login_info.verification_uri} 输入代码: {login_info.user_code}")
    print(f"  等待登录完成...")
    
    future.result()
    
    if session.check_login():
        print(f"  ✓ OAuth验证成功！Token已保存，下次无需再验证")
        # 保存token
        account['token_type'] = session.token_type
        account['access_token'] = session.access_token
        account['refresh_token'] = session.refresh_token
        account['expiry_time'] = str(session.expiry_time)
        save_config()
        return session
    else:
        raise Exception(f"账号 {account_name} 登录失败")


def search_album(session, artist_name, album_name):
    """搜索专辑"""
    search_query = f"{artist_name} {album_name}"
    results = session.search(search_query, models=[tidalapi.album.Album])
    
    albums = None
    if isinstance(results, dict):
        albums = results.get('albums', [])
    elif hasattr(results, 'albums'):
        albums = results.albums
    
    if not albums:
        return None
    
    # 查找匹配的专辑
    for album in albums:
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
            return album
    
    return albums[0] if albums else None


def get_or_create_playlist(session, playlist_name, description=""):
    """获取或创建播放列表"""
    user_playlists = session.user.playlists()
    
    for playlist in user_playlists:
        if playlist.name and playlist.name.lower() == playlist_name.lower():
            return playlist, False
    
    playlist = session.user.create_playlist(playlist_name, description)
    return playlist, True


def add_tracks_to_playlist(playlist, tracks, max_tracks=10):
    """添加歌曲到播放列表"""
    if not tracks:
        return 0
    
    tracks_to_add = tracks[:max_tracks]
    track_ids = [track.id for track in tracks_to_add]
    
    try:
        playlist.add(track_ids)
        return len(tracks_to_add)
    except Exception as e:
        print(f"    ✗ 添加失败: {e}")
        return 0


def process_account(account, index):
    """处理单个账号"""
    account_name = account.get('name', f'账号{index+1}')
    print(f"\n{'='*60}")
    print(f"处理 [{account_name}]")
    print('='*60)
    
    # 登录
    try:
        session = login_account(account, index)
    except Exception as e:
        print(f"  ✗ 登录失败: {e}")
        return False
    
    # 获取或创建播放列表
    playlist, is_new = get_or_create_playlist(
        session,
        config.TARGET_PLAYLIST_NAME,
        config.TARGET_PLAYLIST_DESCRIPTION
    )
    if is_new:
        print(f"  ✓ 创建播放列表: {playlist.name}")
    else:
        print(f"  ✓ 找到播放列表: {playlist.name}")
    
    # 处理每张专辑
    total_added = 0
    for album_info in config.ALBUMS_TO_ADD:
        artist_name = album_info["artist_name"]
        album_name = album_info["album_name"]
        track_count = album_info.get("track_count", 10)
        
        print(f"  搜索: {artist_name} - {album_name}")
        album = search_album(session, artist_name, album_name)
        
        if album:
            tracks = album.tracks()
            added = add_tracks_to_playlist(playlist, tracks, track_count)
            total_added += added
            album_display = album.name if hasattr(album, 'name') else str(album)
            print(f"    ✓ 添加 {added} 首歌曲 (来自: {album_display})")
        else:
            print(f"    ✗ 未找到专辑")
    
    print(f"  完成！共添加 {total_added} 首歌曲")
    return True


def main():
    """主函数"""
    print("=" * 60)
    print("Tidal 多账号批量播放列表管理工具")
    print("=" * 60)
    print(f"共 {len(config.ACCOUNTS)} 个账号待处理")
    print(f"目标播放列表: {config.TARGET_PLAYLIST_NAME}")
    print(f"待添加专辑: {len(config.ALBUMS_TO_ADD)} 张")
    
    success_count = 0
    for i, account in enumerate(config.ACCOUNTS):
        if process_account(account, i):
            success_count += 1
    
    # 保存更新后的token
    save_config()
    
    print("\n" + "=" * 60)
    print(f"全部完成！成功处理 {success_count}/{len(config.ACCOUNTS)} 个账号")
    print("Token已保存，下次运行无需再次OAuth验证")
    print("=" * 60)


if __name__ == "__main__":
    main()
