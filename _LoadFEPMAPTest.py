res1 = False
res2 = False
ret_val = False

Gui.ClearGseSerialLog()

jyResetCmd(16,0) # Reset all faults
jyStateCmd(2) # Move to SAFE state

jySetPower(0x80,0x1)

sleeper(5)

ProgramSelectMap("BOARD_ID_IRSTAP2", 0x40000000, "BOARD_ID_IRSTAP2", 0x1)



if res1 and res2:
  ret_val = True

# results is the list that is initialized in
# run_fsw_ci.py. It is used to store test result.
# For consistency, have test name match file name.

# TODO: Set pass/fail parameters
if(ret_val):
  results.append("... PASSED")
else:
  results.append("... FAILED")