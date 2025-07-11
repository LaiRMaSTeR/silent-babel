import easyocr
import cv2
from tqdm import tqdm
from googletrans import Translator
import textwrap
from difflib import SequenceMatcher
import asyncio
import os
import numpy as np
import argparse
import pathlib


def not_timecode(text):
    number_count = len([e for e in text if e.isdigit()])
    if number_count / len(text) > 0.5:
        return False
    return True


def get_text_from_movie(path, lang='fr'):
    buffer = cv2.VideoCapture(path)
    fps = int(round(buffer.get(cv2.CAP_PROP_FPS)))  # How bad will this get for FPS drops or some shit like 23.998??
    frame_count = int(buffer.get(cv2.CAP_PROP_FRAME_COUNT))
    intertitles = []  # (start_time, end_time, text)
    pbar = tqdm(desc="Getting text from movie file.", leave=True, total=frame_count)
    counter = 0
    intertitle_len_counter = 0
    old_parahraph = None
    reader = easyocr.Reader([lang])
    while buffer.isOpened():
        ret, frame = buffer.read()
        if ret:
            if counter % (fps // 2) == 0:
                result = reader.readtext(frame, paragraph=True, detail=0)
                if result:
                    result = [e for e in result if not_timecode(e)]
                    paragraph = ' '.join(result)
                    intertitle_len_counter += fps // 2
                    if old_parahraph is None:
                        old_parahraph = paragraph
                    elif SequenceMatcher(None, paragraph, old_parahraph).ratio() < 0.9:
                        intertitles.append(((counter - intertitle_len_counter) / fps, counter / fps, old_parahraph))
                        intertitle_len_counter = 0
                        old_parahraph = paragraph
                
                elif intertitle_len_counter != 0:
                    intertitles.append(((counter - intertitle_len_counter) / fps, counter / fps, paragraph))
                    intertitle_len_counter = 0
                    old_parahraph = None

            counter += 1
            pbar.update(1)
            if counter > 60*24:
                break
        else:
            break
    
    buffer.release()
    pbar.close()
    return intertitles


async def translate(intertitles, lang_in='fr', lang_out='en'):
    text = [e[2] for e in intertitles]
    translated_intertitles = []
    async with Translator() as translator:
        translations = await translator.translate(text, dest=lang_out, src=lang_in)
        for i, e in enumerate(translations):
            translated_intertitles.append((intertitles[i][0], intertitles[i][1], e.text))

    return translated_intertitles


def seconds_to_timestamp(seconds):
    miliseconds = int(1000 * (seconds - int(seconds)))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int((seconds % 3600) % 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{miliseconds:03}"


def generate_srt(intertitles, path):
    if os.path.splitext(path)[1] != ".srt":
        path = f"{os.path.splitext(path)[0]}.srt"

    line_counter = 1
    with open(path, 'w') as f:
        for intertitle in intertitles:
            wrapped = textwrap.wrap(intertitle[2], 50)
            timeline = np.linspace(intertitle[0], intertitle[1], len(wrapped) + 1)
            for i, line in enumerate(wrapped):
                f.write(str(line_counter) + '\n')
                timecode = f"{seconds_to_timestamp(timeline[i])} --> {seconds_to_timestamp(timeline[i + 1])}\n"
                f.write(timecode)
                f.write(line + '\n\n')
                line_counter += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Get intertitles from video file, translate to english and save as .srt")
    parser.add_argument('--language', '-l', type=str, required=True, help="Original langauge code of intertitles (usually 2-letter codes, e.g. 'en', 'fr', 'es', refer to googletrans module documentation for full list)")
    parser.add_argument('--target', '-t', required=False, default='en', type=str, help="Language of the output. Defaults to english.")
    parser.add_argument('-output', '-o', type=str, required=False, help="Output path for .srt. If not given, file will be saved alongside input file.")
    parser.add_argument('files', metavar='files', nargs='+', type=str, help='Patha to files with movies.')
    namespace = parser.parse_args()

    for file in namespace.files:
        file = pathlib.Path(file)
        file.resolve()
        print(f"Working on {file}:")
    
        if namespace.output is None:
            output = file
        else:
            output = namespace.output

        intertitles = get_text_from_movie(file)
        print("Translating...")
        translation = asyncio.run(translate(intertitles, namespace.language, namespace.target))
        print("Generating .srt...")
        generate_srt(translation, output)
