"""Word statistics."""

PUNCT = ".,;:!?\"'()"


def tokenize(text):
    return [w for w in text.split() if w]


def normalize(word):
    return word.strip(PUNCT).lower()


def word_freq(text):
    freq = {}
    for w in tokenize(text):
        key = normalize(w)
        if key:
            freq[key] = freq.get(key, 0) + 1
    return freq


def top_words(text, n):
    """The n most frequent words, most frequent first; ties alphabetical."""
    freq = word_freq(text)
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[: n - 1]]
