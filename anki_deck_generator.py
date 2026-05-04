from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile
import genanki
from html import escape
import argparse

class AnkiDeckCreator:

    MODEL_ID = 1607392319
    MODEL_NAME = '1CNIKtoAnki'
    DEFAULT_CSS = '''
        .card {
            font-family: "Segoe UI", "Calibri", Arial, sans-serif;
            font-size: 17px;
            color: #1a1a1a;
            background: #ffffff;
            padding: 35px 40px;
            max-width: 720px;
            margin: 0 auto;
            line-height: 1.6;
            border: 1px solid #d0d0d0;
            border-radius: 0;
        }

        .question-text {
            font-size: 18px;
            font-weight: 600;
            color: #000000;
            padding: 0 0 18px 0;
            margin-bottom: 22px;
            border-bottom: 1px solid #999999;
        }

        .options-list {
            list-style: none;
            padding: 0;
            margin: 0;
            counter-reset: option;
        }

        .option-item {
            padding: 10px 0 10px 0;
            margin: 0;
            color: #1a1a1a;
            border: none;
            border-bottom: 1px solid #e6e6e6;
        }

        .option-item::before {
            counter-increment: option;
            content: counter(option) ".";
            display: inline-block;
            width: 28px;
            font-weight: 600;
            color: #333333;
        }

        hr {
            border: none;
            height: 1px;
            background: #999999;
            margin: 28px 0;
        }

        .answer-label {
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #4d4d4d;
            margin-bottom: 10px;
        }

        .correct-answer {
            font-size: 20px;
            font-weight: 700;
            color: #1a7a2e;
            padding: 0;
            background: none;
            border-left: 3px solid #1a7a2e;
            padding-left: 16px;
            margin: 0;
        }

        .comment-block {
            margin-top: 24px;
            padding: 0 0 0 16px;
            border-left: 1px solid #cccccc;
            color: #4d4d4d;
            font-size: 15px;
            line-height: 1.6;
        }
    '''

    def __init__(self, data, unload_way, css = DEFAULT_CSS):
        
        self.data = data
        self.unload_way = unload_way
        self.css = css
        self.temp_dirs = []

        fields=[
            {'name': 'Question'},
            {'name': 'Options'},
            {'name': 'CorrectAnswer'},
            {'name': 'Comment'},
        ]

        templates = [{
            'name': 'Карточка',
            'qfmt': '''
                <div class="question-text">{{Question}}</div>
                <ul class="options-list">{{Options}}</ul>
            ''',
            'afmt': '''
                <div class="question-text">{{Question}}</div>
                <ul class="options-list">{{Options}}</ul>
                <hr>
                <div class="answer-label">Правильный ответ</div>
                <div class="correct-answer">{{CorrectAnswer}}</div>
                {{#Comment}}
                <div class="comment-block">{{Comment}}</div>
                {{/Comment}}
            ''',
        }] 

        self.model = genanki.Model(self.MODEL_ID, 
                                   self.MODEL_NAME, 
                                   fields, 
                                   templates, 
                                   self.css)
   
    def get_package(self, output_file):
        
        count = 0
        all_decks = []
        all_media_files = []
        root_deck = None

        try:

            for exam in self.data:
                if exam.get("Тип") != "Экзамен":
                    continue
                exam_id = exam.get("УД")
                exam_media_way = exam.get("КаталогДанных")
                root_deck_name = exam.get("Наименование")
                root_deck_id = self.id_for_deck(root_deck_name)
                root_deck = genanki.Deck(root_deck_id, root_deck_name)
                for section in exam.get("Разделы", []):
                    if section.get("Тип") != "Раздел":
                        continue
                    section_name = section.get("Наименование", "Без раздела").strip()
                    subdeck_name = f"{root_deck_name}::{section_name}"
                    deck_id = self.id_for_deck(subdeck_name)
                    subdeck = genanki.Deck(deck_id, subdeck_name)

                    for q in section.get("Вопросы", []):
                        if q.get("Тип") != "Вопрос":
                            continue
                        question_id = q.get("УД")
                        question_html = self.build_question_html(q, question_id, exam_media_way, exam_id, all_media_files)
                        question_com = self.build_comment_html(q, question_id, exam_media_way, exam_id, all_media_files)
                        correct_text = ""
                        options_parts = []
                        for answer in q.get("Ответы", []):
                            if answer.get("Тип") != "Ответ":
                                continue
                            ans_text = self.clean_html(answer.get("Текст", ""))
                            options_parts.append(f'<li class="option-item">{ans_text}</li>')                                                 
                            if answer.get("Правильный", False):
                                correct_text = ans_text
                        options_html = "".join(options_parts)
                        tags = [section_name.replace(" ", "_")]

                        note = genanki.Note(
                            model=self.model,
                            fields=[question_html, options_html, correct_text, question_com], 
                            tags=tags
                        ) 
                        subdeck.add_note(note)
                        count += 1
                    all_decks.append(subdeck)

            all_decks.insert(0, root_deck)

            package = genanki.Package(all_decks)
            package.media_files = all_media_files
            package.write_to_file(output_file)

        finally:
            self.cleanup_temp_files()

    def cleanup_temp_files(self):

        for temp_dir in self.temp_dirs:
            try:
                if Path(temp_dir).exists():
                    shutil.rmtree(temp_dir)
                    print(f"Удалена временная папка: {temp_dir}")
            except Exception as e:
                print(f"Ошибка при удалении {temp_dir}: {e}")
        self.temp_dirs.clear()

    def id_for_deck(self, deck_name):
        deck_id = abs(hash(deck_name)) % (2**31 - 1)  
        return deck_id

    def clean_html(self, raw_html):
        if not raw_html or not raw_html.strip():
            return ""
        if '<html' not in raw_html and '<body' not in raw_html:
            return escape(raw_html.strip())
        body_match = re.search(r'<body[^>]*>(.*?)</body>', raw_html, re.DOTALL | re.IGNORECASE)
        if body_match:
            return body_match.group(1).strip()
        content = re.sub(r'<!DOCTYPE[^>]*>', '', raw_html, flags=re.IGNORECASE)
        content = re.sub(r'<html[^>]*>|</html>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<head>.*?</head>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<meta[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        return content.strip()

    def build_comment_html(self, q, question_id, exam_media_way, exam_id, all_media):

        if not q.get("ЕстьКомментарийZIP", False):
            raw = q.get("Комментарий", "")
            return raw
        
        question_media_dir = self.unload_way / exam_media_way / exam_id

        if not question_media_dir.exists():
            return ""
        
        zip_file = None

        for ext in ('.zip', '.ZIP'):
            candidate = question_media_dir / f"{question_id}{ext}"
            if candidate.exists():
                zip_file = candidate
                break
        
        if not zip_file:
            return ""
        
        tmp_dir = tempfile.mkdtemp()
        self.temp_dirs.append(tmp_dir)

        try:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                
                html_name = None
                img_names = []
                
                for name in zf.namelist():
                    ext = Path(name).suffix.lower()
                    if ext in ('.html', '.htm'):
                        html_name = name
                    elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.bmp', '.tif'):
                        img_names.append(name)
                
                if not html_name:
                    return ""
                
                zf.extractall(tmp_dir)
            
            for img_name in img_names:
                src = Path(tmp_dir) / img_name
                if src.exists():
                    new_name = f"c{question_id}_{Path(img_name).name}"
                    dst = Path(tmp_dir) / new_name
                    shutil.copy2(src, dst)
                    all_media.append(str(dst))
            
            html_path = Path(tmp_dir) / html_name
            with open(html_path, 'r', encoding='utf-8') as f:
                raw_html = f.read()
            
            comment_html = self.clean_html(raw_html)
            
            for img_name in img_names:
                old_src = Path(img_name).name
                new_src = f"c{question_id}_{Path(img_name).name}"
                comment_html = re.sub(
                    rf'src=["\']{re.escape(old_src)}["\']',
                    f'src="{new_src}"',
                    comment_html
                )
            
            return comment_html
        
        except Exception as e:
            print(f"Ошибка при обработке комментария для вопроса {question_id}: {e}")
            return ""
    
    def build_question_html(self, q, question_id, exam_media_way, exam_id, all_media):
    
        raw_text = q.get("Текст") or q.get("Наименование", "Нет текста")
        text_html = self.clean_html(raw_text)
        
        if not q.get("ЕстьИллюстрация", False):
            return text_html

        question_media_dir = self.unload_way / exam_media_way / exam_id
        
        if not question_media_dir.exists():
            return text_html
        
        img_file = None

        for ext in ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.bmp', '.tif'):
            candidate = question_media_dir / f"{question_id}{ext}"
            if candidate.exists():
                img_file = candidate
                break
        
        if not img_file:
            return text_html
        
        all_media.append(str(img_file))

        img_tag = f'<img src="{img_file.name}" style="max-width:100%; height:auto; margin:10px 0;">'

        return f"{text_html}{img_tag}"
            
    
def main():
    
    parser = argparse.ArgumentParser(description='Создание anki колоды')
    parser.add_argument('-f', '--file', required=True, help='Путь к файлу с вопросами')
    parser.add_argument('-d', '--data', required=True, help='Путь к директории содержащей выгрузку данных из приложения ""ru.publishing1c.nik""')
    parser.add_argument('-r', '--result', required=True, help='Путь сохранения результата')
    parser.add_argument('-c', '--css', required=False, help='Путь к файлу с стилями .css')

    argums = parser.parse_args()

    if argums.file is None or argums.data is None or argums.result is None: 
        print('Не все обязательные параметры заполненны')
        return
     
    with open(argums.file, "r", encoding="utf=8") as file:
        data = json.load(file)

    unload_path = Path(argums.data)

    if argums.css is None:
                anki_creator = AnkiDeckCreator(data, unload_path)
    else:
        with open(argums.css, "r", encoding="utf-8") as css_file:
            css_content = css_file.read()
        anki_creator = AnkiDeckCreator(data, unload_path, css_content)

    anki_creator.get_package(argums.result) 


if __name__ == '__main__':
    main()
