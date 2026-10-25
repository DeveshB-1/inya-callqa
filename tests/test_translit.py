from inya_callqa.translit import has_indic, phonetic_key, scripts_in, sound_similarity, to_latin


def test_devanagari_with_nukta_and_schwa_deletion():
    assert to_latin("मच") == "mach"  # final schwa dropped in Hindi
    assert to_latin("इज़") == "iz"  # nukta turns j into z
    assert to_latin("हाउ मच इज़ माइ ड्यू अमाउंट") == "haau mach iz maai dyuu amaaunt"


def test_kannada_keeps_final_vowel():
    assert to_latin("ನನ್ನ ಆರ್ಡರ್") == "nanna aardar"
    assert to_latin("ಬೇಕು") == "beku"


def test_script_detection():
    assert scripts_in("EMI ₹४५०० बाकी") == {"latin", "devanagari"}
    assert has_indic("ಮಾಡಿ") and not has_indic("cancel")


def test_english_spelling_and_transliteration_meet_in_the_key():
    assert phonetic_key("cancel maadi") == phonetic_key("ಕ್ಯಾನ್ಸಲ್ ಮಾಡಿ")
    assert phonetic_key("mera paisa kab wapas aayega") == phonetic_key("मेरा पैसा कब वापस आएगा")


def test_similarity_separates_same_sound_from_different_words():
    same = sound_similarity("how much is my due amount", "हाउ मच इज़ माइ ड्यू अमाउंट")
    different = sound_similarity("yes you are", "येस शुर")
    unrelated = sound_similarity("i already paid last week", "मैं कल पे कर दूंगा")
    assert same > 0.9
    assert different < 0.75
    assert unrelated < 0.4
