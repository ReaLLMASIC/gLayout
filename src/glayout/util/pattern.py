
def check_pattern_level(pattern):

    if isinstance(pattern, list):

        if isinstance(pattern[0], list):

            if isinstance(pattern[0][0], list):
                raise ValueError("Maximum level for pattern (2) exceeded" )
            else:
                return 2
        else:
            return 1

    else:
        return 0

def check_pattern_size(pattern):

    return tuple([len(pattern[0]), len(pattern)] )

def transpose_pattern(pattern):

    if check_pattern_level(pattern)==2:

        return list(map(list,zip(*pattern)))

    else:
        raise ValueError("Transpose not supported for other dimension than 2")


def flatten_array(pattern):
    return sum(pattern, [])

def get_cols_positions(pattern):

    unique_elements=list(set(flatten_array(pattern)))

    element_cols = dict()
    t_pattern = transpose_pattern(pattern)
    for element in unique_elements:
        p_cols = []
        for col, v_pattern in enumerate(t_pattern):
            if element in v_pattern:
                p_cols.append(col)
        element_cols[element]=p_cols

    return element_cols

