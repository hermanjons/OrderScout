import sys
import os
import shutil
import time
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QProgressBar, QPushButton, QLabel, QMessageBox
from PyQt6.QtCore import QRunnable, QThreadPool, pyqtSignal, QObject

import requests
import tempfile
import zipfile


class WorkerSignals(QObject):
    progress = pyqtSignal(str)
    progress_bar = pyqtSignal(int)
    finished = pyqtSignal()


class UpdateWorker(QRunnable):
    def __init__(self, base_directory, download_url, database_directory_name):
        super().__init__()
        self.base_dir = base_directory
        self.download_url = download_url
        self.downloaded_zip_path = None
        self.extracted_update_files_path = None
        self.database_directory_name = database_directory_name

        self.excluded_files = ["update_script.py", self.database_directory_name, "update_script.exe"]

        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.progress.emit("Güncelleme işlemi başlıyor...")
            self.download_update()
            self.extract_update()
            self.apply_update()
            self.cleanup_update_files()
            self.signals.finished.emit()

        except Exception as e:
            self.signals.progress.emit(f"Güncelleme işlemi sırasında bir hata oluştu: {str(e)}")

    def download_update(self):
        try:
            response = requests.get(self.download_url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            chunk_size = 1024

            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
                for data in response.iter_content(chunk_size=chunk_size):
                    tmp_file.write(data)
                    downloaded_size += len(data)

                    if total_size > 0:
                        progress_percentage = int((downloaded_size / total_size) * 100)
                        self.signals.progress.emit(f"Download Progress: {progress_percentage}%")
                        self.signals.progress_bar.emit(progress_percentage)
                    else:
                        self.signals.progress.emit(f"Downloaded: {downloaded_size} bytes")

                self.downloaded_zip_path = tmp_file.name

        except requests.exceptions.RequestException as e:
            raise Exception(f"An error occurred while downloading the update: {str(e)}")

    def extract_update(self):
        try:
            extract_path = "update_files"
            with zipfile.ZipFile(self.downloaded_zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            os.remove(self.downloaded_zip_path)
            self.downloaded_zip_path = None

            self.extracted_update_files_path = extract_path
        except zipfile.BadZipFile as e:
            raise Exception(f"An error occurred while extracting the update: {str(e)}")

    def apply_update(self):
        version_file_path = os.path.join(self.base_dir, "version.txt")
        try:
            with open(version_file_path, "r") as version_file:
                version_name = version_file.readline().strip().lstrip("v.")
        except FileNotFoundError:
            version_name = "0.0"

        backup_dir = os.path.join(self.base_dir, f"backup_{version_name}")
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        for filename in os.listdir(self.base_dir):
            file_path = os.path.join(self.base_dir, filename)

            # backup_dir'in alt klasörü olup olmadığını kontrol et
            if filename != "update_script.py" and filename != "update_files" and not os.path.commonpath(
                    [file_path, backup_dir]) == backup_dir and\
                    "backup" not in filename and filename != "update_script.exe":

                backup_path = os.path.join(backup_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        shutil.copy2(file_path, backup_path)
                    elif os.path.isdir(file_path):
                        shutil.copytree(file_path, backup_path)
                    self.signals.progress.emit(f"{filename} yedeklendi.")
                except Exception as e:
                    self.signals.progress.emit(f"{filename} yedeklenemedi. Hata: {str(e)}")

        subdirectories = [d for d in os.listdir(self.extracted_update_files_path)
                          if os.path.isdir(os.path.join(self.extracted_update_files_path, d))]
        if len(subdirectories) == 1:
            update_subdir = os.path.join(self.extracted_update_files_path, subdirectories[0])
        else:
            update_subdir = self.extracted_update_files_path
            raise Exception("Update directory should contain exactly one subdirectory.")



        total_files = len([f for f in os.listdir(update_subdir) if f not in self.excluded_files])
        current_file = 0

        for filename in os.listdir(update_subdir):
            if filename not in self.excluded_files:
                src_path = os.path.join(update_subdir, filename)
                dest_path = os.path.join(self.base_dir, filename)
                try:
                    if os.path.isdir(src_path):
                        if os.path.exists(dest_path):
                            shutil.rmtree(dest_path)
                        shutil.copytree(src_path, dest_path)
                    else:
                        shutil.copy2(src_path, dest_path)
                    current_file += 1
                    progress_percentage = int((current_file / total_files) * 100)
                    self.signals.progress.emit(f"{filename} taşındı.")
                    self.signals.progress.emit(f"Güncelleme tamamlanma yüzdesi: {progress_percentage}%")
                except Exception as e:
                    self.signals.progress.emit(f"{filename} taşınamadı. Hata: {str(e)}")

    def cleanup_update_files(self):
        if os.path.exists(self.extracted_update_files_path):
            try:
                shutil.rmtree(self.extracted_update_files_path)
                self.signals.progress.emit("Güncelleme dosyaları temizlendi.")
            except Exception as e:
                self.signals.progress.emit(f"Güncelleme dosyaları temizlenirken bir hata oluştu: {str(e)}")


class UpdateWindow(QWidget):
    def __init__(self, base_directory, download_url, dbase_directory_name, latest_version_name):
        super().__init__()
        self.base_dir = base_directory
        self.download_url = download_url
        self.database_directory_name = dbase_directory_name
        self.latest_version = latest_version_name
        self.progress_label = QLabel("Güncelleme işlemi başlıyor...")
        self.progress_bar = QProgressBar()
        self.cancel_button = QPushButton("İptal")

        self.ok_button = QPushButton("OK")

        self.threadpool = QThreadPool()




        self.init_ui()
        self.start_update()

    def init_ui(self):
        self.setWindowTitle("Güncelleme İşlemi")
        self.setGeometry(100, 100, 400, 200)



        self.progress_bar.setRange(0, 100)
        self.cancel_button.clicked.connect(self.close)
        self.ok_button.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.ok_button)


        self.ok_button.setVisible(False)

        self.setLayout(layout)
        self.show()

    @staticmethod
    def read_current_version():
        try:
            with open("version.txt", "r") as file:
                return file.readline().strip().lstrip("v.")
        except FileNotFoundError:
            return "0.0.0"

    def start_update(self):
        if self.latest_version > self.read_current_version():
            print(self.read_current_version(), ":", self.latest_version)

            worker = UpdateWorker(self.base_dir, self.download_url, self.database_directory_name)
            worker.signals.progress.connect(self.update_progress)
            worker.signals.progress_bar.connect(self.update_progress_bar)
            worker.signals.finished.connect(self.on_update_finished)
            self.threadpool.start(worker)
        elif self.latest_version == self.read_current_version():
            self.progress_label.setText("Güncelleme zaten tamamlandı")

        else:
            self.progress_label.setText("Güncelleme işleminde bir hata oluşmuş.programın temiz haline tekrar indirin")

    def update_progress(self, message):
        self.progress_label.setText(message)

    def update_progress_bar(self, value):
        self.progress_bar.setValue(value)

    def on_update_finished(self):
        self.progress_label.setText("Güncelleme tamamlandı.")
        self.cancel_button.setVisible(False)
        self.ok_button.setVisible(True)



if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Kullanım: python update_script.py <base_dir> <download_url> <database_directory_name> <latest_version>")
        sys.exit(1)

    base_dir = sys.argv[1]
    down_url = sys.argv[2]
    dbase_dir_name = sys.argv[3]
    latest_version = sys.argv[4]

    app = QApplication(sys.argv)
    window = UpdateWindow(base_dir, down_url, dbase_dir_name, latest_version)
    sys.exit(app.exec())
