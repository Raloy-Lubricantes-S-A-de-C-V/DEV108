import re

text = "{{CONDITION:NUEVO_RENOVACIO\nN_REASIGNACION}}\n\n{{MAIL_PERSONALIZADO_GENERI\nCO}}"

key1 = "CONDITION"
pattern1 = r"\{\{" + re.escape(key1) + r"(?::.*?)?\}\}"
print("Match 1:", re.findall(pattern1, text, re.DOTALL))

key2 = "MAIL_PERSONALIZADO_GENERICO"
pattern2 = r"\{\{" + re.escape(key2) + r"(?::.*?)?\}\}"
print("Match 2:", re.findall(pattern2, text, re.DOTALL))

# How to match key with newlines?
# Insert \s* between every character of the key
key2_regex = r"\s*".join(re.escape(char) for char in key2)
pattern2_flex = r"\{\{" + key2_regex + r"(?::.*?)?\}\}"
print("Match 2 flex:", re.findall(pattern2_flex, text, re.DOTALL))

