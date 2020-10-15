import os
import argparse
import pysrt
import re
from googletrans import Translator
from fuzzywuzzy import fuzz
import ffmpeg
import tempfile
import subliminal
from babelfish import Language
from subliminal.core import AsyncProviderPool

OPENSUBTITLES_CREDENTIALS = {
    'username': os.environ['OS_USERNAME'], 'password': os.environ['OS_PASSWORD']}


class SubArguments:
    def __init__(self):
        self.reference = None
        self.input = None
        self.output = None
        self._usable_reference = None
        self._usable_input = None


def validate_args(args: SubArguments):
    if not os.path.exists(args.reference):
        raise FileNotFoundError

    if args.input and args.input.endswith('.srt'):
        args._usable_input = args.input
    if args.reference and args.reference.endswith('.srt'):
        args._usable_reference = args.reference

    if args.output is None and args.input is not None:
        filename_list = args.input.split('.')
        filename_list.insert(-1, 'synced')
        args.output = '.'.join(filename_list)


def remove_os_markings(parsed_input):
    for sub in parsed_input:
        if re.search('opensubtitles', sub.text, flags=re.IGNORECASE) is not None:
            parsed_input.remove(sub)


def process_compare_and_shift(args: SubArguments):
    parsed_reference = pysrt.open(args._usable_reference)
    parsed_input = pysrt.open(args._usable_input)

    remove_os_markings(parsed_input)

    sliced_reference = parsed_reference.slice(ends_before={'minutes': 10})
    first_sub_input = parsed_input[0]

    translator = Translator()
    first_sub_translated = translator.translate(first_sub_input.text)
    print(f'Translated first subtitle: {first_sub_translated.text}')

    time_shift = 0
    high_match_sub = first_sub_translated
    high_match_score = 0
    for sub in sliced_reference:
        match_score = fuzz.token_set_ratio(sub.text, first_sub_translated.text)
        if match_score > high_match_score:
            high_match_score = match_score
            high_match_sub = sub

    if high_match_score > 90:
        time_shift = high_match_sub.start - first_sub_input.start

    print(f'Shifting subtitles by {time_shift}')
    parsed_input.shift(minutes=time_shift.minutes,
                       seconds=time_shift.seconds,
                       milliseconds=time_shift.milliseconds)

    parsed_input.clean_indexes()

    return parsed_input


def extract_subtitles_from_mkv(args: SubArguments, temp_dir):
    sub_path = os.path.join(temp_dir, 'included_sub.srt')

    probe = ffmpeg.probe(args.reference)
    sub_stream = next((stream for stream in probe['streams'] if (
        stream['codec_type'] == 'subtitle' and stream['tags']['language'] == 'eng')), None)
    sub_index = str(sub_stream['index'])
    input_mm = ffmpeg.input(args.reference)

    print(f'Extracting embeded subtitle to {sub_path}')
    out, _ = ffmpeg.output(input_mm[sub_index],
                           sub_path).run(capture_stdout=True)

    args._usable_reference = sub_path


def download_subtitles(args: SubArguments):
    languages = set()
    if not args._usable_reference:
        languages.add(Language('eng'))
    if not args._usable_input:
        languages.add(Language('spa'))

    if languages != {}:
        provider = ['opensubtitles']
        provider_configs = {'opensubtitles': OPENSUBTITLES_CREDENTIALS}
        video = subliminal.scan_video(args.reference)
        with AsyncProviderPool(providers=provider, provider_configs=provider_configs) as p:
            subtitles = p.download_best_subtitles(subtitles=p.list_subtitles(video, languages),
                                                  video=video, languages=languages)

        saved_subtitles = subliminal.save_subtitles(video, subtitles)
        for subtitle in saved_subtitles:
            if subtitle.language == Language('eng'):
                args._usable_reference = subtitle.get_path(video)
            if subtitle.language == Language('spa'):
                args._usable_input = subtitle.get_path(video)
                args.output = subtitle.get_path(video)


def main():
    sub_args = SubArguments()
    parser = argparse.ArgumentParser(prog="Subsync translate")
    parser.add_argument("reference", help="Reference subtitle or video")
    parser.add_argument("-i", "--input", help="Path to the subtitle that is going to be synced",
                        dest="input")
    parser.add_argument("-o", "--output", help="Path for the output subtitle",
                        dest="output")
    parser.parse_args(namespace=sub_args)

    validate_args(sub_args)

    with tempfile.TemporaryDirectory() as dir_path:
        if not sub_args._usable_reference:
            extract_subtitles_from_mkv(sub_args, dir_path)

        download_subtitles(sub_args)

        result_sub = process_compare_and_shift(sub_args)

        if os.path.exists(sub_args.output):
            os.remove(sub_args.output)
        result_sub.save(sub_args.output)


if __name__ == "__main__":
    main()
