"""Unit tests for RTF text decoding: \\'hh escapes in the code page of their font."""
from rvt_prt.elements.annotations import rtf_to_text
from rvt_prt.elements.titleblock import rtf_lines

# a TextNote of 2019/サンプル構造.rvt: Shift-JIS runs in \f0 (\fcharset128), Latin in \f1
JAPANESE = ("{\\rtf1\\ansi\\ansicpg932\\deff0\\nouicompat\\deflang1033\\deflangfe1041\\deftab170"
            "{\\fonttbl{\\f0\\fnil\\fcharset128 Meiryo UI;}{\\f1\\fnil\\fcharset0 Meiryo UI;}}\r\n"
            "{\\colortbl ;\\red0\\green0\\blue0;}\r\n{\\*\\generator Riched20 10.0.17134}\\viewkind4\\uc1 \r\n"
            "\\pard\\cf1\\f0\\fs12\\'81\\'45\\'83\\'58\\'83\\'89\\'83\\'75\\f1   S\\par\r\n}\r\n")
WESTERN = "{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\\pard\\f0\\fs20 Caf\\'e9 \\'b0C\\par}"


def test_double_byte_text():
    assert rtf_to_text(JAPANESE) == ("・スラブ  S", 6.0)
    assert rtf_lines(JAPANESE)[0][0][0] == "・スラブ  S"


def test_western_text():
    assert rtf_to_text(WESTERN) == ("Café °C", 10.0)
    assert rtf_lines(WESTERN)[0][0][0] == "Café °C"


def test_unicode_escapes():
    # \uN then \uc characters for readers without Unicode, skipped: the cover of サンプル意匠.rvt
    # showed "(建?築?図?)"
    rtf = "{\\rtf1\\ansi\\uc1\\pard\\f0\\fs20 (\\u24314?\\u31689?\\u22259?)\\uc2\\u-28675\\'8c\\'a7 x\\par}"
    assert rtf_lines(rtf)[0][0][0] == "(建築図)\u8ffd x"
