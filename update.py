import re
import os
from urllib.parse import urljoin
import requests
import yt_dlp

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.cnnturk.com/"
}

def resolve_dogan_media(page_url):
    """Doğan Medya (CNN Türk, Kanal D, Teve2 vb.) sitelerinden content_id bularak API üzerinden link çözer."""
    try:
        # 1. Ana sayfayı çek ve data-content-id veya data-live alanlarını ara
        r = requests.get(page_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        
        html_text = r.text
        
        # Doğrudan data-url içinde m3u8 arama (Streamlink mantığı _get_hls_url)
        match_hls = re.search(r'data-url="([^"]+\.m3u8[^"]*)"', html_text)
        if match_hls:
            return match_hls.group(1).replace("&amp;", "&")

        # 2. Content ID bulma (Streamlink _get_content_id mantığına benzer regex yakalama)
        # Genellikle div içinde data-id veya body içinde data-content-id olarak yer alır
        content_id_match = re.search(r'data-content-id=["\']([^"\']+)["\']', html_text)
        if not content_id_match:
            content_id_match = re.search(r'data-id=["\']([^"\']+)["\'][^>]*data-live', html_text)
        
        if not content_id_match:
            # Alternatif ID kalıpları
            content_id_match = re.search(r'["\']contentId["\']\s*:\s*["\']([^"\']+)["\']', html_text)
            
        if not content_id_match:
            return None
            
        content_id = content_id_match.group(1)
        
        # 3. Streamlink'in kullandığı olası API endpoint listesi
        api_urls = [
            f"/api/media?id={content_id}",
            f"/actions/content/media/{content_id}",
            f"/action/media/{content_id}",
            f"/actions/media?id={content_id}"
        ]
        
        # Domain adresini kök URL olarak al (Örn: https://www.cnnturk.com)
        from urllib.parse import urlparse
        parsed_uri = urlparse(page_url)
        base_domain = f"{parsed_uri.scheme}://{parsed_uri.netloc}"

        for api_path in api_urls:
            full_api_url = urljoin(base_domain, api_path)
            try:
                r_api = requests.get(full_api_url, headers=headers, timeout=5)
                if r_api.status_code == 200:
                    data = r_api.json()
                    
                    # Yeni tip API yanıtı kontrolü
                    media = data.get("Media", {})
                    if not media and "data" in data:  # Eski tip API yanıtı ihtimali
                        media = data.get("data", {}).get("media", {})
                        
                    link_obj = media.get("Link", {}) or media.get("link", {})
                    
                    service_url = link_obj.get("ServiceUrl") or link_obj.get("serviceUrl") or ""
                    default_service_url = link_obj.get("DefaultServiceUrl") or link_obj.get("defaultServiceUrl") or ""
                    secure_path = link_obj.get("SecurePath") or link_obj.get("securePath") or ""
                    stream_url_direct = link_obj.get("StreamUrl") or link_obj.get("streamUrl") or ""

                    if stream_url_direct:
                        return stream_url_direct.replace("&amp;", "&")

                    if secure_path:
                        if re.match(r"^https?://", secure_path):
                            return secure_path.replace("&amp;", "&")
                        
                        target_base = service_url or default_service_url
                        if target_base:
                            return urljoin(target_base, secure_path).replace("&amp;", "&")
            except Exception:
                continue

    except Exception as e:
        print(f"Doğan Medya API çözümleme hatası: {e}")
        
    return None

def resolve_stream_url(url):
    """Gelen bağlantı türüne göre canlı yayın m3u8 adresini çözer."""
    
    # 1. Doğrudan m3u8, mpd veya bilinen canlı akış CDN linki ise DİREKT DÖN
    if ".m3u8" in url or ".mpd" in url or "artidijitalmedya.com" in url:
        return url

    # 2. Cine1 Altyapısı
    if "cine1.com.tr" in url:
        try:
            r = requests.get("https://cine1.com.tr/", headers=headers, timeout=10)
            match = re.search(r'(https://canliyayin\.cine1\.com\.tr/memfs/[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', r.text)
            if match:
                return match.group(1).replace("&amp;", "&")
        except Exception as e:
            print(f"Cine1 hatası: {e}")
        return None

    # 3. Doğan Medya / CNN Türk / Kanal D / Teve2 Altyapısı (Streamlink Mantığı + Duhnet)
    if any(domain in url for domain in ["cnnturk", "kanald", "teve2", "dreamturk", "dreamtv", "duhnet"]):
        try:
            # a) İlk olarak özel CNN Türk direkt canlı yayın API'sini dene
            api_url = "https://www.cnnturk.com/api/cnnvideo/media?id=62d6814670380e2cdc7c124c&isMobile=true"
            r_api = requests.get(api_url, headers=headers, timeout=10)
            if r_api.status_code == 200:
                data = r_api.json()
                media = data.get("Media", {})
                if "StreamUrl" in media and media["StreamUrl"]:
                    return media["StreamUrl"].replace("&amp;", "&")
                
                service_url = media.get("ServiceUrl", "")
                secure_path = media.get("SecurePath", "")
                if service_url and secure_path:
                    return (service_url + secure_path).replace("&amp;", "&")

            # b) Doğrudan API yanıt vermezse, verdiğiniz Streamlink mantığını (Content-ID & çoklu endpoint taramasını) çalıştır
            stream_from_dogan = resolve_dogan_media(url)
            if stream_from_dogan:
                return stream_from_dogan

            # c) En son yedek olarak web sayfasını genel regex ile tara
            r = requests.get(url, headers=headers, timeout=10)
            match_token = re.search(r'(https?://[^\s"\'<>]*duhnet\.tv[^\s"\'<>]*\.m3u8\?[^\s"\'<>]+)', r.text)
            if match_token:
                return match_token.group(1).replace("&amp;", "&")

            match_plain = re.search(r'(https?://[^\s"\'<>]*duhnet\.tv[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', r.text)
            if match_plain:
                return match_plain.group(1).replace("&amp;", "&")

        except Exception as e:
            print(f"Doğan/Duhnet çözme hatası: {e}")

    # 4. YouTube / Dailymotion Canlı Yayınları (yt-dlp)
    if "youtube.com" in url or "youtu.be" in url or "dailymotion.com" in url:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'best',
            'http_headers': headers
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get('url')
        except Exception as e:
            print(f"yt-dlp hatası ({url}): {e}")
        return None

    # 5. Genel Regex Taraması
    try:
        r = requests.get(url, headers=headers, timeout=10)
        match = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', r.text)
        if match:
            return match.group(1).replace("&amp;", "&")
    except Exception as e:
        print(f"Genel regex hatası ({url}): {e}")

    return None

def main():
    if not os.path.exists("channels.txt"):
        print("[HATA] channels.txt dosyası bulunamadı!")
        return

    m3u_lines = ["#EXTM3U\n"]
    updated_channels_lines = []

    with open("channels.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        line_str = line.strip()
        
        if not line_str or line_str.startswith("#"):
            updated_channels_lines.append(line_str)
            continue

        parts = [p.strip() for p in line_str.split("|")]
        name = parts[0]
        url = parts[1]
        group = parts[2] if len(parts) > 2 and parts[2] else "Genel"
        logo = parts[3] if len(parts) > 3 and parts[3] else ""

        print(f"[{name}] İşleniyor...")
        stream_url = resolve_stream_url(url)

        if stream_url:
            m3u_lines.append(f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}')
            m3u_lines.append(f'{stream_url}\n')
            print(f"  -> Başarılı: {stream_url[:60]}...")
            
            updated_line = f"{name} | {stream_url} | {group} | {logo}"
            updated_channels_lines.append(updated_line)
        else:
            print("  -> BAŞARISIZ! Bağlantı çözülemedi.")
            updated_channels_lines.append(line_str)

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))

    with open("channels.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(updated_channels_lines) + "\n")
        
    print("\n[BİLGİ] İşlem tamamlandı. 'channels.txt' ve 'playlist.m3u' güncellendi.")

if __name__ == "__main__":
    main()
