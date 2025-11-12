import ast 
import os 
import sys 
import re 
from typing import List, Dict, Set, Optional, Tuple, Any 
from collections import defaultdict 
class CompleteStructureCommenter:# beginclass
	"""A more robust Python structure commenter that handles multi-block endings."""
		
	
		
	def __init__(self):# beginmethod
		self.source_lines = [] 
		self.result_lines = [] 
		self.begin_comments = {}#  Line -> [comments]
		self.end_comments = defaultdict(list)#  Line -> [(comment, indentation, start_line)]
		# endmethod
	def add_comments(self, filename: str, output_filename: Optional[str] = None) -> str:# beginmethod
		"""Add structural comments to a Python file."""
		#  Read the file
		with open(filename, 'r', encoding='utf-8') as f:# beginwith
		
			content = f.read() 
			# endwith
		return self.add_comments_to_string(content, output_filename) 
		# endmethod
	def add_comments_to_string(self, content: str, output_filename: Optional[str] = None) -> str:# beginmethod
		"""Add structural comments to a Python string."""
		#  Parse the content
		self.source_lines = content.splitlines() 
		#  Parse the AST, first clean up content with special characters
		try:# begintry
		
			#  Replace asterisks in identifiers for AST parsing only
			clean_content = re.sub(r'\*([a-zA-Z0-9_]+)\*', r'\1', content) 
			tree = ast.parse(clean_content) 
		except SyntaxError as e: 
			print(f"Syntax error in input file: {e}")#// //
			input("enter to continue") ;
			return content 
			# endtry
		#  First pass: collect all the begin/end comments
		self._collect_comments(tree) 
		#  Second pass: apply the comments to the source lines
		self._apply_comments() 
		#  Create the modified content
		modified_content = '\n'.join(self.result_lines) 
		#  Write to output file if provided
		if output_filename:# beginif
		
			with open(output_filename, 'w', encoding='utf-8') as f:# beginwith
			
				f.write(modified_content) 
				# endwith
			# endif
		return modified_content 
		# endmethod
	def _get_indent(self, line_idx: int) -> str:# beginmethod
		"""Get the indentation of a line."""
		if line_idx < 0 or line_idx >= len(self.source_lines):# beginif
		
			return "" 
			# endif
		line = self.source_lines[line_idx] 
		return line[:len(line) - len(line.lstrip())] 
		# endmethod
	def _collect_comments_for_node(self, node, node_type, begin_comment, end_comment):# beginmethod
		"""Collect begin and end comments for a specific node."""
		if not hasattr(node, 'lineno') or not hasattr(node, 'end_lineno'):# beginif
		
			return 
			# endif
		start_line = node.lineno - 1 
		end_line = node.end_lineno - 1 
		indent = self._get_indent(start_line) 
		#  Add begin comment
		if start_line not in self.begin_comments:# beginif
		
			self.begin_comments[start_line] = [] 
			# endif
		self.begin_comments[start_line].append(begin_comment) 
		#  Add end comment - store as (comment, indentation, start_line)
		#  The start_line is used for sorting end comments when multiple blocks end on the same line
		self.end_comments[end_line].append((end_comment, indent, start_line)) 
		# endmethod
	def _collect_comments(self, tree):# beginmethod
		"""First pass: collect all the begin/end comments."""
		#  Clear previous comments
		self.begin_comments = {} 
		self.end_comments = defaultdict(list) 
		#  Build a mapping of nodes to their parent
		parent_map = {} 
		for parent in ast.walk(tree):# beginfor
			for child in ast.iter_child_nodes(parent):# beginfor
				parent_map[child] = parent 
				# endfor
			
			# endfor
		
		#  Collect comments from all nodes in AST order
		for node in ast.walk(tree):# beginfor
			#  Function definitions
			if isinstance(node, ast.FunctionDef):# beginif
			
				#  Check if this is a method inside a class
				parent = parent_map.get(node) 
				if parent and isinstance(parent, ast.ClassDef):# beginif
				
					self._collect_comments_for_node(node, "method", "#beginmethod", "#endmethod") 
				else: 
					self._collect_comments_for_node(node, "function", "#beginfunc", "#endfunc") 
					# endif
				#  Class definitions
			elif isinstance(node, ast.ClassDef):# beginelif
				self._collect_comments_for_node(node, "class", "#beginclass", "#endclass") 
				#  If statements
			elif isinstance(node, ast.If):# beginelif
				#  Check if this is an elif by examining the source line
				start_line = node.lineno - 1 
				if start_line < len(self.source_lines):# beginif
				
					line = self.source_lines[start_line].strip() 
					if line.startswith("elif "):# beginif
					
						self._collect_comments_for_node(node, "elif", "#beginelif", "#endlif") 
					else: 
						self._collect_comments_for_node(node, "if", "#beginif", "#endif") 
						# endif
				else: 
					#  Fallback if we can't determine
					self._collect_comments_for_node(node, "if", "#beginif", "#endif") 
					# endif
				#  For loops
			elif isinstance(node, ast.For):# beginelif
				self._collect_comments_for_node(node, "for", "#beginfor", "#endfor") 
				#  While loops
			elif isinstance(node, ast.While):# beginelif
				self._collect_comments_for_node(node, "while", "#beginwhile", "#endwhile") 
				#  With statements
			elif isinstance(node, ast.With):# beginelif
				self._collect_comments_for_node(node, "with", "#beginwith", "#endwith") 
				#  Try-except blocks
			elif isinstance(node, ast.Try):# beginelif
				self._collect_comments_for_node(node, "try", "#begintry", "#endtry") 
				# endlif
				# endlif
				# endlif
				# endlif
				# endlif
				# endlif
				# endif
			# endfor
		
		# endmethod
	def _should_skip_comment(self, line, comment_tag):# beginmethod
		"""
		Check if we should skip adding a comment because it's already in the line, 
		but make sure we don't skip if it's only inside a string literal. 
		"""
		if comment_tag not in line:# beginif
		
			return False#  Not in line at all, don't skip
			# endif
		#  Identify positions of string literals in the line
		str_positions = [] 
		#  Find double-quoted strings
		for match in re.finditer(r'"[^"\\]*(?:\\.[^"\\]*)*"', line):# beginfor
			str_positions.append((match.start(), match.end())) 
			# endfor
		
		#  Find single-quoted strings
		for match in re.finditer(r"'[^'\\]*(?:\\.[^'\\]*)*'", line):# beginfor
			str_positions.append((match.start(), match.end())) 
			# endfor
		
		#  Find all occurrences of the comment tag
		for match in re.finditer(re.escape(comment_tag), line):# beginfor
			tag_start = match.start() 
			tag_end = match.end() 
			#  Check if this occurrence is inside any string literal
			inside_string = False 
			for str_start, str_end in str_positions:# beginfor
				if str_start <= tag_start and tag_end <= str_end:# beginif
				
					inside_string = True 
					break 
					# endif
				# endfor
			
			if not inside_string:# beginif
			
				return True#  Found a real comment outside string literals, skip adding
				# endif
			# endfor
		
		return False#  All instances were inside string literals, don't skip
		# endmethod
	def _apply_comments(self):# beginmethod
		"""Second pass: apply the comments to the source lines."""
		self.result_lines = [] 
		#  Process each line
		for i, line in enumerate(self.source_lines):# beginfor
			#  First add the original line (possibly with begin comments)
			if i in self.begin_comments:# beginif
			
				#  Need to add begin comments
				begin_comments = self.begin_comments[i] 
				begin_comment_str = " ".join(begin_comments)
				#  Check if line already has a comment
				if '#' in line and not line.strip().startswith('#'):# beginif
				
					#  Check if any of our begin comments already exist in the line outside string literals
					should_skip = any(self._should_skip_comment(line, comment) for comment in begin_comments) 
					if should_skip:# beginif
					
						#  If real comments exist, parse out existing comment
						comment_pos = line.find('#') 
						code_part = line[:comment_pos].rstrip() 
						existing_comment = line[comment_pos:] 
						#  Add our begin comments before the existing comment
						#begin_comment_str = " ".join(begin_comments)
						modified = f"{code_part} {begin_comment_str} {existing_comment}" 
						self.result_lines.append(modified) 
					else: 
						#  No existing structure comments (or only in string literals)
						self.result_lines.append(f"{line} {begin_comment_str}") 
						# endif
				else: 
					#  No existing comment, add to end
					#begin_comment_str = " ".join(begin_comments)
					self.result_lines.append(f"{line} {begin_comment_str}") 
					# endif
			else: 
				#  No begin comment to add
				self.result_lines.append(line) 
				# endif
			#  Then check if we need to add end comments after this line
			if i in self.end_comments:# beginif
			
				#  Sort end comments by their start line - this ensures proper nesting
				#  Blocks that started later (higher start_line) should be closed first
				sorted_end_comments = sorted(#// //
				
					self.end_comments[i], 
					key=lambda x: x[2],#  Sort by start_line
					reverse=True#  Later blocks should be closed first
					)#// //
				#  Add each end comment on its own line
				for end_comment, indent, _ in sorted_end_comments:# beginfor
					self.result_lines.append(f"{indent}{end_comment}") 
					# endfor
				
				# endif
			# endfor
		
		# endmethod
		
	# endclass
#  Extended lists to include the new endif/endlif distinction
Ends = [ 

	"endfunc", 
	"endmethod", 
	"endclass", 
	"endif", 
	#"endlif",  # Added for elif statements# 0,  # Added for elif statements
	"endwith", 
	"endtry", 
	"endfor", 
	"endwhile", 
	]#// //
Begins = [#// //

	"beginfunc", 
	"beginmethod", 
	"beginclass", 
	"beginif", 
	"beginelif",#  Added for elif statements
	"begintry", 
	"beginwith", 
	"beginwhile", 
	"beginfor", 
	]#// //
#  Update the begin_type mapping to include beginelif
begin_type = {#//// ////

	"beginfunc": "input", 
	"beginmethod": "input", 
	"beginclass": "event", 
	"beginif": "branch", 
	"beginelif": "branch",#  Same type as beginif
	"begintry": "branch", 
	"beginwith": "branch", 
	"beginwhile": "loop", 
	"beginfor": "loop", 
	}#// //
#  Update the end_type mapping to include endlif
end_type = {#// //

	"endfunc": "end", 
	"endmethod": "end", 
	"endclass": "end", 
	"endif": "bend", 
	#"endlif": "bend",  # Same type as endif# 0: 0,  # Same type as endif
	"endwith": "bend", 
	"endtry": "bend", 
	"endfor": "lend", 
	"endwhile": "lend", 
	}#// //
path_type = [#// //

	"elif",#  for if
	"else",#  for if, try, loops
	"except",#  for try
	"finally",#  for try
	]#// //
event_type = [#// //

	"import", 
	"from", 
	]#// //
output_type = [#// //

	"print", 
	".write", 
	]#// //
VFCSEPERATOR = ';//' 
def is_path(line: str) -> bool:# beginfunc
	"""
	Return True if the first word of the given line is one of the path type. 
	"""
	parts = line.strip().split(None, 1) 
	if not parts:# beginif
	
		return False 
		# endif
	if parts[0].strip(" :") in path_type:# beginif
	
		return True 
		# endif
	# endfunc
def replace_string_literals(input_string):# beginfunc
	#  Regular expression to match both single and double-quoted string literals
	result = re.sub(r'(["\'])(.*?)(\1)', '0', input_string)
	return result 
	# endfunc
def split_on_comment(input_string):# beginfunc
	#  Regular expression to match the comment outside of quotes
	match = re.search(r'(?<!")#.*$', temp_str)
	if match:# beginif
	
		s1 = input_string.strip()#  Everything before the comment
		s2 = match.strip()#  The comment itself
	else: 
		s1, s2 = input_string.strip(), "" 
		# endif
	return (s1, s2) 
	# endfunc
def split_string(input_string):# beginfunc
	temp_str = replace_string_literals(input_string) 
	parts = temp_str.split("#", 1)  # Split at the first occurrence of '#'#  Split at the first occurrence of 0
	# parts = split_on_comment(input_string)
	s1 = input_string.strip() 
	if len(parts) > 1 :# beginif
	
		s2 = parts[1] 
		s1 = s1.replace('#'+s2, "") 
	else: 
		s2 = ""#  s2 holds the second part, or remains empty
		# endif
	return (s1, s2) 
	# endfunc
def get_marker( comment ):# beginfunc
	parts = comment.strip().split(None, 1) 
	if not parts:# beginif
	
		return "none" 
		# endif
	marker = parts[0] 
	return marker 
	# endfunc
def get_VFC_type(code : str, line: str) -> Optional[str]:# beginfunc
	"""
	If the first word of `line` (without any leading '#') is in Begins or Ends, 
	returns its mapped type; otherwise returns None. 
	"""
	token = code.strip().split(None, 1)[0] if len(code) > 1 else "none" 
	if token in event_type:# beginif
	
		return "event" 
		# endif
	if is_path(code):# beginif
	
		return 'path' 
		# endif
	parts = line.strip().split(None, 1) 
	if not parts:# beginif
	
		return "set" 
		# endif
	marker = parts[0] 
	if marker in Begins:# beginif
	
		return begin_type[marker] 
		# endif
	if marker in Ends:# beginif
	
		return end_type[marker] 
		# endif
	return "set" 
	# endfunc
def generate_VFC(input_string):# beginfunc
	strings = input_string.split("\n")#  Splits the input at each newline
	VFC = '' 
	for string in strings:# beginfor
		#  Skip empty lines
		if not string.strip():# beginif
		
			continue 
		else:
			string = ''.join(c if c.isascii() else ' ' for c in string)
			# endif
		code, comment = split_string(string) 
		code = code.strip() 
		type = get_VFC_type(code, comment) 
		marker = get_marker( comment ) 
		## PRE FIX TOKENS# # PRE FIX TOKENS 
		if marker == "endclass" :# beginif
		
			VFC += f"bend(){VFCSEPERATOR}\n" 
			# endif
		
		VFC += f'{type}({code}){VFCSEPERATOR} { comment.replace( marker, "" , 1 ) }\n'#// //
		## POST FIX TOKENS# # POST FIX TOKENS 
		if type == "branch":# beginif
		
			VFC += f"path(){VFCSEPERATOR}\n" 
			# endif
		if marker == "beginclass" :# beginif
		
			VFC += f"branch(){VFCSEPERATOR}\n" 
			VFC += f"path(){VFCSEPERATOR}\n" 
			VFC += f"path(){VFCSEPERATOR}\n" 
			# endif
		# endfor
	
	return VFC 
	# endfunc
def main():# beginfunc
	import argparse 
	parser = argparse.ArgumentParser(description='Add structure comments to Python code') 
	parser.add_argument('input_file', help='Input Python file') 
	parser.add_argument('-o', '--output', help='Output file (default: stdout)') 
	args = parser.parse_args() 
	commenter = CompleteStructureCommenter() 
	modified_code = commenter.add_comments(args.input_file, args.output) 
	VFC = generate_VFC(modified_code) 
	root_filename = os.path.splitext(os.path.basename( args.input_file  ))[0]  + '.py'# ////
	with open(args.input_file+'.vfc', 'w') as VFC_output:# beginwith
	
		VFC_output.write(VFC) 
		VFC_output.write( 
		";INSECTA EMBEDDED SESSION INFORMATION\n"+ 
		"; 255 16777215 65280 16777088 16711680 13158600 16777088 0 255 255 65535 6946660 986895\n"+ 
		f"; { root_filename }      #    '\n"+ 
		"; notepad.exe\n"+ 
		";INSECTA EMBEDDED ALTSESSION INFORMATION\n"+ 
		"; 260 260 1130 1751 0 130   137   4294966452    python.key  0" 
		)
		# endwith
	return modified_code 
	# endfunc
if __name__ == '__main__':# beginif

	t = main() 
	# endif
#  Export  Date: 07:18:35 PM - 11:Nov:2025.

