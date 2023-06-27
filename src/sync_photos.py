"""Sync photos module."""
___author___ = "Mandar Patil <mandarons@pm.me>"
import base64
import os
import shutil
import time

from icloudpy import exceptions

from src import LOGGER, PHOTO_DATA, UID, GID, config_parser, save_photo_data

from tzlocal import get_localzone


EXT_LOOKUP_TABLE = {
    'public.png': 'PNG',
    'public.mpeg-4': 'MP4',
    'public.jpeg': 'JPEG',
    'com.apple.quicktime-movie': 'MOV',
    'public.heic': 'HEIC',
    'com.sony.arw-raw-image': 'ARW',
    'org.webmproject.webp': 'WEBP',
    'com.compuserve.gif': 'GIF',
    'com.adobe.raw-image': 'DNG',
    'public.tiff': 'TIFF',
    'public.jpeg-2000': 'JP2',
    'com.truevision.tga-image': 'TGA',
    'com.sgi.sgi-image': 'SGI',
    'com.adobe.photoshop-image': 'PSD',
    'public.pbm': 'PBM',
    'public.heif': 'HEIF',
    'com.microsoft.bmp': 'BMP',
    'public.mpeg': 'MPG',
    'com.apple.m4v-video': 'M4V',
    'public.3gpp': '3GP',
    'public.mpeg-2-video': 'M2V',
    'com.fuji.raw-image': 'RAF',
    'com.canon.cr2-raw-image': 'CR2',
    'com.panasonic.rw2-raw-image': 'RW2',
    'com.nikon.nrw-raw-image': 'NRW',
    'com.pentax.raw-image': 'PEF',
    'com.nikon.raw-image': 'NEF',
    'com.olympus.raw-image': 'ORF',
    'public.avi': 'AVI'
}


def photo_wanted(photo, extensions):
    """Check if photo is wanted based on extension."""
    if not extensions or len(extensions) == 0:
        return True
    for extension in extensions:
        if photo.filename.lower().endswith(str(extension).lower()):
            return True
    return False


def generate_file_name(photo, file_size, destination_path, folder_structure, duplicate_id=-1):
    """Generate full path to file."""
    try:
        filedate = photo.created.astimezone(get_localzone())
    except (ValueError, OSError):
        LOGGER.error(f"Could not convert photo created date to local timezone ({photo.created})")
        filedate = photo.created
        
    foldername = folder_structure.format(filedate)
    folderpath = os.path.join(destination_path, foldername)
    if not os.path.exists(folderpath):
        os.makedirs(folderpath)
        os.chown(folderpath, UID, GID)
    name, extension = photo.filename.rsplit(".", 1)
    if file_size == "original_alt":
        extension = EXT_LOOKUP_TABLE.get(photo.versions[file_size]['type'], 'JPEG')
    if duplicate_id == -1:
        filename = f"{name}.{extension}" if file_size in [ "original", "original_alt" ] else f"{name}_{file_size}.{extension}"
    else:
        filename = f"{name}_{duplicate_id}.{extension}" if file_size in [ "original", "original_alt" ] else f"{name}_{file_size}_{duplicate_id}.{extension}"
    file_path = os.path.join(folderpath, filename)

    return file_path


def download_photo(photo, file_size, destination_path):
    """Download photo from server."""
    if not (photo and file_size and destination_path):
        return False
    LOGGER.info(f"Downloading {destination_path} ...")
    try:
        download = photo.download(file_size)
        with open(destination_path, "wb") as file_out:
            shutil.copyfileobj(download.raw, file_out)
        local_modified_time = time.mktime(photo.added_date.timetuple())
        os.utime(destination_path, (local_modified_time, local_modified_time))
    except (exceptions.ICloudPyAPIResponseException, FileNotFoundError, Exception) as e:
        LOGGER.error(f"Failed to download {destination_path}: {str(e)}")
        return False
    try:
        os.chown(destination_path, UID, GID)
    except:
        LOGGER.error(f"Failed to chown {destination_path}")
    return True


def process_photo(photo, file_size, destination_path, folder_structure):
    """Process photo details."""
    if file_size not in photo.versions:
        return False
    photo_id = photo.id
    photo_size = int(photo.versions[file_size]["size"])
    photo_checksum = photo.versions[file_size]["checksum"]
    if photo_id in PHOTO_DATA:
        photo_data = PHOTO_DATA[photo_id]
        if photo_data["size"] == photo_size and photo_data["checksum"] == photo_checksum:
            LOGGER.debug(f"No changes detected. Skipping the file {photo_data['path']} ...")
            return False
        else:
            photo_path = photo_data["path"]
            if download_photo(photo, file_size, photo_path):
                PHOTO_DATA[photo_id] = photo_data
    else:
        duplicate_id = -1
        while True:
            photo_path = generate_file_name(
                photo=photo, file_size=file_size, destination_path=destination_path, folder_structure=folder_structure, duplicate_id=duplicate_id
            )
            if os.path.isfile(photo_path):
                if os.path.getsize(photo_path) == photo_size:
                    LOGGER.debug(f"No changes detected. Skipping the file {photo_path} ...")
                    PHOTO_DATA[photo_id] = {"path":photo_path, "size": photo_size, "checksum": photo_checksum}
                    return False
                else:
                    LOGGER.warning(f"Duplicate file {photo_path}, find next valid path ...")
                    duplicate_id = duplicate_id + 1
            else:
                if download_photo(photo, file_size, photo_path):
                    PHOTO_DATA[photo_id] = {"path":photo_path, "size": photo_size, "checksum": photo_checksum}
    return True


def sync_album(album, destination_path, folder_structure, file_sizes, extensions=None):
    """Sync given album."""
    if album is None or destination_path is None or folder_structure is None or file_sizes is None:
        return None
    os.makedirs(destination_path, exist_ok=True)
    os.chown(destination_path, UID, GID)
    process_photo_count = 0
    for photo in album:
        if photo_wanted(photo, extensions):
            for file_size in file_sizes:
                process_photo(photo, file_size, destination_path, folder_structure)
                process_photo_count = process_photo_count + 1
                if process_photo_count >= 100:
                    save_photo_data(PHOTO_DATA)
                    process_photo_count = 0
        else:
            LOGGER.debug(f"Skipping the unwanted photo {photo.filename}.")
    for subalbum in album.subalbums:
        sync_album(
            album.subalbums[subalbum],
            os.path.join(destination_path, subalbum),
            file_sizes,
            extensions,
        )
    return True


def sync_photos(config, photos):
    """Sync all photos."""
    destination_path = config_parser.prepare_photos_destination(config=config)
    filters = config_parser.get_photos_filters(config=config)
    folder_structure = config_parser.get_photos_folder_structure(config=config)
    remove_obsolete = config_parser.get_photos_remove_obsolete(config=config)
    if filters["albums"]:
        for album in iter(filters["albums"]):
            sync_album(
                album=photos.albums[album],
                destination_path=os.path.join(destination_path, album),
                folder_structure=folder_structure,
                file_sizes=filters["file_sizes"],
                extensions=filters["extensions"],
            )
    else:
        sync_album(
            album=photos.all,
            destination_path=destination_path,
            folder_structure=folder_structure,
            file_sizes=filters["file_sizes"],
            extensions=filters["extensions"],
        )
    remove_obsolete_photos(photos.deleted, dry=not remove_obsolete)
    save_photo_data(PHOTO_DATA)
    
    
def remove_obsolete_photos(deleted_album, dry):
    """Remove obsolete photos."""
    for photo in deleted_album:
        if photo.id in PHOTO_DATA:
            photo_data = PHOTO_DATA[photo.id]
            if dry:
                LOGGER.info(f"Delete {photo_data['path']} ...")
            else:
                del PHOTO_DATA[photo.id]
                if os.path.isfile(photo_data['path']):
                    os.remove(photo_data['path'])

# def enable_debug():
#     import contextlib
#     import http.client
#     import logging
#     import requests
#     import warnings

#     # from pprint import pprint
#     # from icloudpy import ICloudPyService
#     from urllib3.exceptions import InsecureRequestWarning

#     # Handle certificate warnings by ignoring them
#     old_merge_environment_settings = requests.Session.merge_environment_settings

#     @contextlib.contextmanager
#     def no_ssl_verification():
#         opened_adapters = set()

#         def merge_environment_settings(self, url, proxies, stream, verify, cert):
#             # Verification happens only once per connection so we need to close
#             # all the opened adapters once we're done. Otherwise, the effects of
#             # verify=False persist beyond the end of this context manager.
#             opened_adapters.add(self.get_adapter(url))

#             settings = old_merge_environment_settings(
#                 self, url, proxies, stream, verify, cert
#             )
#             settings["verify"] = False

#             return settings

#         requests.Session.merge_environment_settings = merge_environment_settings

#         try:
#             with warnings.catch_warnings():
#                 warnings.simplefilter("ignore", InsecureRequestWarning)
#                 yield
#         finally:
#             requests.Session.merge_environment_settings = old_merge_environment_settings

#             for adapter in opened_adapters:
#                 try:
#                     adapter.close()
#                 except Exception as e:
#                     pass

#     # Monkeypatch the http client for full debugging output
#     httpclient_logger = logging.getLogger("http.client")

#     def httpclient_logging_patch(level=logging.DEBUG):
#         """Enable HTTPConnection debug logging to the logging framework"""

#         def httpclient_log(*args):
#             httpclient_logger.log(level, " ".join(args))

#         # mask the print() built-in in the http.client module to use
#         # logging instead
#         http.client.print = httpclient_log
#         # enable debugging
#         http.client.HTTPConnection.debuglevel = 1

#     # Enable general debug logging
#     logging.basicConfig(filename="log1.txt", encoding="utf-8", level=logging.DEBUG)

#     httpclient_logging_patch()


# if __name__ == "__main__":
#     # enable_debug()
#     sync_photos()
