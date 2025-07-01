code_128_char_set = {
    "00": " ",
    "01": "!",
    "02": '"',
    "03": "#",
    "04": "$",
    "05": "%",
    "06": "&",
    "07": "'",
    "08": "(",
    "09": ")",
    "10": "*",
    "11": "+",
    "12": ",",
    "13": "-",
    "14": ".",
    "15": "/",
    "16": "0",
    "17": "1",
    "18": "2",
    "19": "3",
    "20": "4",
    "21": "5",
    "22": "6",
    "23": "7",
    "24": "8",
    "25": "9",
    "26": ":",
    "27": ";",
    "28": "<",
    "29": "=",
    "30": ">",
    "31": "?",
    "32": "@",
    "33": "A",
    "34": "B",
    "35": "C",
    "36": "D",
    "37": "E",
    "38": "F",
    "39": "G",
    "40": "H",
    "41": "I",
    "42": "J",
    "43": "K",
    "44": "L",
    "45": "M",
    "46": "N",
    "47": "O",
    "48": "P",
    "49": "Q",
    "50": "R",
    "51": "S",
    "52": "T",
    "53": "U",
    "54": "V",
    "55": "W",
    "56": "X",
    "57": "Y",
    "58": "Z",
    "59": "[",
    "60": "\\",
    "61": "]",
    "62": "^",
    "63": "_",
    "64": "`",
    "65": "a",
    "66": "b",
    "67": "c",
    "68": "d",
    "69": "e",
    "70": "f",
    "71": "g",
    "72": "h",
    "73": "i",
    "74": "j",
    "75": "k",
    "76": "l",
    "77": "m",
    "78": "n",
    "79": "o",
    "80": "p",
    "81": "q",
    "82": "r",
    "83": "s",
    "84": "t",
    "85": "u",
    "86": "v",
    "87": "w",
    "88": "x",
    "89": "y",
    "90": "z",
    "91": "{",
    "92": "|",
    "93": "}",
    "94": "~",
    "95": "Ã",
    "96": "Ä",
    "97": "Å",
    "98": "Æ",
    "99": "Ç",
    "100": "È",
    "101": "É",
    "102": "Ê",
    "103": "Ë",
    "104": "Ì",
    "105": "Í"

}


def encode_code_128(data):
    try:

        encoded_data = ""
        encoded_data = encoded_data + chr(205)

        for i in range(0, len(data), 2):
            two_char = data[i:i + 2]
            encoded_data = encoded_data + code_128_char_set[two_char]
        check_sum = calculate_check_sum(data)
        encoded_data = encoded_data + check_sum + chr(206)
        return encoded_data
    except Exception as e:
        return "error|"+str(e)


def calculate_check_sum(data):
    cnt = 1

    total_of_numbers = 105

    for i in range(0, len(data), 2):
        two_char = data[i:i + 2]
        total_of_numbers += int(two_char) * cnt
        cnt += 1

    modal_output = str(total_of_numbers % 103)
    if len(modal_output) == 1:
        modal_output = "0" + modal_output
    else:
        pass
    check_sum_char = code_128_char_set[modal_output]

    return check_sum_char
