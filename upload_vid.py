import os
import http.client
import httplib2
import random
import sys
import time
from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow
import argparse

CLIENT_SECRETS_FILE = "client_secrets.json"
PLAYLIST_TITLE = "cybertech"

httplib2.RETRIES = 1
MAX_RETRIES = 10
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError, http.client.NotConnected,
                        http.client.IncompleteRead, http.client.ImproperConnectionState,
                        http.client.CannotSendRequest, http.client.CannotSendHeader,
                        http.client.ResponseNotReady, http.client.BadStatusLine)
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Please configure OAuth 2.0

To make this sample run, you will need to populate the client_secrets.json file
found at:

   %s

with information from the API Console
https://console.cloud.google.com/

For more information about the client_secrets.json file format, please visit:
https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
""" % os.path.abspath(os.path.join(os.path.dirname(__file__), CLIENT_SECRETS_FILE))

VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")

def get_authenticated_service(client_secrets_file):
    flow = flow_from_clientsecrets(client_secrets_file,
                                   scope=YOUTUBE_UPLOAD_SCOPE,
                                   message=MISSING_CLIENT_SECRETS_MESSAGE)
    storage = Storage("%s-oauth2.json" % sys.argv[0])
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        credentials = run_flow(flow, storage, argparser.parse_args([]))

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                 http=credentials.authorize(httplib2.Http()))

def create_or_get_playlist(youtube):
    playlists = youtube.playlists().list(part="snippet", mine=True).execute()
    for playlist in playlists["items"]:
        if playlist["snippet"]["title"] == PLAYLIST_TITLE:
            return playlist["id"]

    # If the playlist doesn't exist, create it
    playlist_request = youtube.playlists().insert(
        part="snippet",
        body=dict(
            snippet=dict(
                title=PLAYLIST_TITLE,
                description="Playlist for cybertech videos"
            )
        )
    )
    playlist_response = playlist_request.execute()
    return playlist_response["id"]

def initialize_upload(youtube, options, playlist_id):
    tags = None
    if options.keywords:
        tags = options.keywords.split(",")

    body = dict(
        snippet=dict(
            title=options.title,
            description=options.description,
            tags=tags,
            categoryId=options.category
        ),
        status=dict(
            privacyStatus=options.privacyStatus
        )
    )

    insert_request = youtube.videos().insert(
        part=",".join(list(body.keys())),
        body=body,
        media_body=MediaFileUpload(options.file, chunksize=-1, resumable=True)
    )

    resumable_upload(insert_request, youtube, playlist_id)

def resumable_upload(insert_request, youtube, playlist_id):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print("Uploading file...")
            status, response = insert_request.next_chunk()
            if response is not None:
                if 'id' in response:
                    print("Video id '%s' was successfully uploaded." % response['id'])
                    # Add video to the specified playlist
                    youtube.playlistItems().insert(
                        part="snippet",
                        body=dict(
                            snippet=dict(
                                playlistId=playlist_id,
                                resourceId=dict(
                                    kind="youtube#video",
                                    videoId=response['id']
                                )
                            )
                        )
                    ).execute()
                else:
                    exit("The upload failed with an unexpected response: %s" % response)
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = "A retriable HTTP error %d occurred:\n%s" % (e.resp.status, e.content)
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = "A retriable error occurred: %s" % e

        if error is not None:
            print(error)
            retry += 1
            if retry > MAX_RETRIES:
                exit("No longer attempting to retry.")

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            print("Sleeping %f seconds and then retrying..." % sleep_seconds)
            time.sleep(sleep_seconds)

def edit_and_upload_video(video_file, title, keywords, client_secrets_file):
    youtube = get_authenticated_service(client_secrets_file)

    playlist_id = create_or_get_playlist(youtube)

    args = argparse.Namespace(
        file=video_file,
        title=title,
        description="Test Description",
        category="22",
        keywords=keywords,
        privacyStatus="public"
    )

    try:
        initialize_upload(youtube, args, playlist_id)
    except HttpError as e:
        print("An HTTP error %d occurred:\n%s" % (e.resp.status, e.content))

def find_and_upload_videos(root_directory, client_secrets_file):
    for foldername, subfolders, filenames in os.walk(root_directory):
        for filename in filenames:
            if filename.lower().endswith(('.mp4', '.avi', '.mov')):
                video_file = os.path.join(foldername, filename)
                txt_file = os.path.join(foldername, f'{os.path.splitext(filename)[0]}.txt')
                thumbnail_file = os.path.join(foldername, f'{os.path.splitext(filename)[0]}.jpg')

                if os.path.exists(txt_file):
                    with open(txt_file, 'r') as txt_file_content:
                        content = txt_file_content.read().strip()
                        if '#' in content:
                            title, keywords = content.split('#', 1)
                            title = title.strip()
                            keywords = keywords.strip()
                        else:
                            title = content
                            keywords = ""

                        print(f"Processing Video: {video_file}, Title: {title}, Keywords: {keywords}")
                        edit_and_upload_video(video_file, title, keywords, client_secrets_file)

if __name__ == '__main__':
    root_directory = '/sdcard/insta'  # Replace with your folder path
    find_and_upload_videos(root_directory, CLIENT_SECRETS_FILE)
