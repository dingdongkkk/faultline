from textstats.core import top_words, tokenize, word_freq


def test_tokenize():
    assert tokenize("a  b c") == ["a", "b", "c"]


def test_freq_counts_case_insensitively():
    assert word_freq("The cat. the CAT!") == {"the": 2, "cat": 2}


def test_freq_ignores_punctuation_only_tokens():
    assert word_freq("hi -- there") == {"hi": 1, "--": 1, "there": 1}


def test_top_words_empty():
    assert top_words("", 3) == []


def test_top_words():
    assert top_words("b a b c a b", 2) == ["b", "a"]
