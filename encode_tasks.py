


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
