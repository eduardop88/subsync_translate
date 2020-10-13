from ast import parse
import os
import argparse
import pysrt
import re
from googletrans import Translator
from fuzzywuzzy import fuzz
import ffmpeg
import tempfile


def validate_args(args):
    if not os.path.exists(args.reference):
        raise FileNotFoundError
    if not os.path.exists(args.input):
        raise FileNotFoundError
    
    if args.output is None:
        filename_list = args.input.split('.')
        filename_list.insert(-1, 'synced')
        args.output = '.'.join(filename_list)



def remove_os_markings(parsed_input):
    for sub in parsed_input:
        if re.search('opensubtitles', sub.text, flags=re.IGNORECASE) is not None:
            parsed_input.remove(sub)

def process_compare_and_shift(args):
    parsed_reference = pysrt.open(args.reference)
    parsed_input = pysrt.open(args.input)

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

def extract_subtitles_from_mkv(args, temp_dir):
    sub_path = os.path.join(temp_dir, 'included_sub.srt')

    probe = ffmpeg.probe(args.reference)
    sub_stream = next((stream for stream in probe['streams'] if (stream['codec_type'] == 'subtitle' and stream['tags']['language'] == 'eng')), None)
    sub_index = str(sub_stream['index'])
    input_mm = ffmpeg.input(args.reference)

    print(f'Extracting embeded subtitle to {sub_path}')
    out, _ = ffmpeg.output(input_mm[sub_index], sub_path).run(capture_stdout=True)

    args.reference = sub_path


def main():
    parser = argparse.ArgumentParser(prog="Subsync translate")
    parser.add_argument("reference", help="Reference subtitle or video")
    parser.add_argument("input", help="Input subtitle")
    parser.add_argument("-o", "--output", help="Path for the output subtitle",
                        dest="output")
    args = parser.parse_args()

    validate_args(args)

    with tempfile.TemporaryDirectory() as dir_path:
        if args.reference.endswith('.mkv'):
            extract_subtitles_from_mkv(args, dir_path)

        result_sub = process_compare_and_shift(args)
        result_sub.save(args.output)


if __name__ == "__main__":
    main()
