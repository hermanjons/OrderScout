# accounts/views/actions.py
import os
import datetime


from Account.models import ApiAccount
from Core.utils.model_utils import create_records


import shutil
from PyQt6.QtCore import Qt

from Feedback.processors.pipeline import Result


def open_register_dialog(parent=None):
    from Account.views.views import CompanyRegisterDialog
    dialog = CompanyRegisterDialog()
    dialog.exec()
