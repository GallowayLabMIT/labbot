import lxml.etree as ET

import tempfile
import re
import pathlib
import zipfile


def open_word_doc_xml(filename):
    """
    Given a filename to unzip, unzips that file into a
    temporary directory, then uses LXML to generate a tree
    version of the main document XML.

    Args:
    -----
    filename: str
        A string listing the location of the .docx to load
    
    Returns:
    --------
    lmxl.etree
        A tree version of the loaded XML.
    """
    with zipfile.ZipFile(filename) as docx_zip, tempfile.TemporaryDirectory() as tmpdir:
        docx_zip.extract('word/document.xml', tmpdir)
        return ET.parse(str(pathlib.Path(tmpdir) / 'word' / 'document.xml'))

def check_for_bibliography(xml):
    """
    Given an XML tree document, returns if a Zotero bibliography was found.

    Args:
    -----
    xml: lxml.etree.Element
        The tree object to search for the bibliography.
    
    Returns:
    --------
    Boolean:
        True if a bibliography exists, False otherwise
    """
    for elem in root.iter('{*}instrText'):
        if 'ADDIN ZOTERO_BIBL' in elem.text:
            return True
    return False

def scan_for_superscripts(xml):
    """
    Given an XML tree document, attempts to find superscripted text
    that looks like numbers that are not included in Zotero field codes.

    Args:
    -----
    xml: lxml.etree.Element
        The tree object to search through.
    
    Returns:
    --------
    List[Tuple[str, str]]
        A list of suspicious superscripts that may be citations. The first tuple
        value is the superscript itself, whereas the second string is the preceding
        text.
    """
    results = []
    # Use a state machine!
    field_code_count = 0
    inside_citation_fc = False
    inside_superscript = False
    last_superscript_parent = None
    text_context = []
    for elem in root.iter():
        # Check for field code
        if 'fldChar' in elem.tag:
            for key, val in elem.attrib.items():
                if 'fldCharType' in key and val == 'begin':
                    field_code_count += 1
                if 'fldCharType' in key and val == 'end':
                    field_code_count -= 1
                    if inside_citation_fc:
                        inside_citation_fc = False
                    if field_code_count < 0:
                        raise RuntimeError('Unexpected field code format')

        # Check for citation field codes
        if 'instrText' in elem.tag and 'ADDIN ZOTERO_ITEM' in elem.text and field_code_count > 0:
            inside_citation_fc = True
        
        if 'vertAlign' in elem.tag:
            for key, val in elem.attrib.items():
                if 'val' in key and 'superscript' in val:
                    # We're in a superscript! Assign it to our superscript's double parent.
                    # The first parent is the text settings
                    last_superscript_parent = elem.getparent().getparent()
        if elem.tag[-2:] == '}t':
            # Check if we're in a superscript
            if last_superscript_parent is elem.getparent() and last_superscript_parent is not None:
                # We're in a subscript
                print(elem.text)
                # Check that this doesn't have other symbols:
                if re.match(r"^(\d| |[-,])*\d(\d| |[-,])*$", elem.text) is not None and not inside_citation_fc:
                    print('Found lonely superscript:{}'.format(elem.text))
                    results.append((elem.text, ''.join(text_context)))
            # Add to the text context
            text_context.append(elem.text if elem.text is not None else '')
            if len(text_context) > 6:
                del text_context[0]
    return results
                

if __name__ == '__main__':
    xml = open_word_doc_xml('tests/dp2_cj.docx')

    root = xml.getroot()
    print(check_for_bibliography(root))
    print(scan_for_superscripts(root))
        