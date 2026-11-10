(* Paste this body into an OpenPLC Editor Program POU.
   Define the process aliases and local variables in the Variables Table. *)

(* Box_Not_Waiting is the inverse of the actual BoxAtSensor input. *)
Box_Not_Waiting := NOT BoxAtSensor;

(* P/N contacts are one-scan rising/falling edge pulses. *)
Picker_Holding_Box_Rising :=
    NOT Picker_Holding_Box_Previous AND Picker_Holding_Box;
Picker_Moving_Z_Falling :=
    Picker_Moving_Z_Previous AND NOT Picker_Moving_Z;
Picker_Rotating_Falling :=
    Picker_Rotating_Previous AND NOT Picker_Rotating;

(* Rung 1: seal-in branch around the momentary StartButton. *)
Run := SafetyDoor AND (StartButton OR Run);

(* Rung 2: conveyor runs until a box reaches the sensor. *)
Conveyor_Move := Run AND Box_Not_Waiting;

(* Rung 3: use the sensor level so startup with a waiting box is not missed. *)
IF Run AND BoxAtSensor AND NOT Picker_Holding_Box THEN
    Picker_Move_Down := TRUE;
    Picker_Grab := TRUE;
END_IF;

(* Rung 4: P contact = rising edge; RESET coil. *)
IF Run AND Picker_Holding_Box_Rising THEN
    Picker_Move_Down := FALSE;
END_IF;

(* Rung 5: N contact = falling edge; SET/RESET coils. *)
IF Run AND Picker_Moving_Z_Falling AND Picker_Holding_Box THEN
    Picker_Rotate_CCW := TRUE;
    Picker_Rotate_CW := FALSE;
END_IF;

(* Rung 6: N contact = falling edge; RESET/SET/RESET coils. *)
IF Run AND Picker_Rotating_Falling AND Picker_Holding_Box THEN
    Picker_Grab := FALSE;
    Picker_Rotate_CW := TRUE;
    Picker_Rotate_CCW := FALSE;
END_IF;

(* Save contact states for N/P edge detection on the next scan. *)
Picker_Holding_Box_Previous := Picker_Holding_Box;
Picker_Moving_Z_Previous := Picker_Moving_Z;
Picker_Rotating_Previous := Picker_Rotating;
