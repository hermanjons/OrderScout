import requests
import os
import sys


def read_current_version():
    try:
        with open("version.txt", "r") as file:
            return file.readline().strip().lstrip("v.")
    except FileNotFoundError:
        return "0.0"


def check_for_updates():
    # GitHub API URL'si
    repo_url = "https://api.github.com/repos/hermanjons/orderScout_win/releases/latest"

    # Mevcut sürüm numarası

    try:
        response = requests.get(repo_url)
        response.raise_for_status()
        latest_release = response.json()

        return latest_release

    except requests.exceptions.RequestException as e:
        return e




