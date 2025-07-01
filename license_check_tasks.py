import uuid
import platform
import requests
import json
import socket
import uuid
import subprocess
import re

import subprocess
import re
import psutil


def get_physical_mac_addresses():
    mac_address = []
    for interface, ad_res in psutil.net_if_addrs().items():
        for addr in ad_res:
            if addr.family == psutil.AF_LINK:
                mac_address.append((interface, addr.address))
    # return mac_address
    return [["test:test:test:test", "test:test:test:test"]]


def get_os_name():
    os_name = platform.system()
    # return os_name
    return "test os"


def get_computer_name():
    computer_name = socket.gethostname()
    # return computer_name
    return "test computer"


def match_machine_with_license(license_id, api_token):
    res_match_machine = requests.post(
        "https://api.keygen.sh/v1/accounts/mdbsoftcheckaccount/machines",
        headers={
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
            "Authorization": f"Bearer {api_token}"
        },
        data=json.dumps({
            "data": {
                "type": "machines",
                "attributes": {
                    "fingerprint": "{}".format(get_physical_mac_addresses()[0][1]),
                    "platform": "{}".format(get_os_name()),
                    "name": "{}".format(get_computer_name())
                },
                "relationships": {
                    "license": {
                        "data": {
                            "type": "licenses",
                            "id": "{}".format(license_id)
                        }
                    }
                }
            }
        })
    ).json()
    return res_match_machine


def validate_license(license_key):
    res_validate = requests.post(
        "https://api.keygen.sh/v1/accounts/mdbsoftcheckaccount/licenses/actions/validate-key",
        headers={
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json"

        },
        data=json.dumps({
            "meta": {
                "key": "{}".format(license_key),
                "scope": {
                    "fingerprint": "{}".format(get_physical_mac_addresses()[0][1])
                }
            }
        })
    ).json()
    return res_validate


def get_machines_for_license(license_key, api_token):
    url = f"https://api.keygen.sh/v1/accounts/mdbsoftcheckaccount/licenses/{license_key}/machines"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/vnd.api+json"
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        machines = response.json()["data"]
        return machines
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None


def disconnect_license(api_token, machine_id):
    res = requests.delete(
        f"https://api.keygen.sh/v1/accounts/mdbsoftcheckaccount/machines/{machine_id}",
        headers={
            "Accept": "application/vnd.api+json",
            "Authorization": f"Bearer {api_token}"
        }
    )
    return res
