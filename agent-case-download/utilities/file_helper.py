from pathlib import Path


class FileHelper:

    @staticmethod
    def create_folder(folder):

        Path(folder).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write_text(file_name, content):

        with open(file_name, "w", encoding="utf-8") as file:

            file.write(content)