      *================================================================*
      * PAYROLL-CALC: Employee payroll calculator
      * Hand-crafted sample using only supported COBOL constructs.
      * Demonstrates: MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE,
      *   COMPUTE, DISPLAY (incl. NO ADVANCING), PERFORM (simple,
      *   UNTIL, TIMES), IF/ELSE, EVALUATE TRUE, EVALUATE variable,
      *   INITIALIZE, OPEN INPUT, READ AT END, CLOSE, STOP RUN.
      * Sensitive fields: EMP-SSN (high), EMP-SALARY (medium).
      *================================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL-CALC.
       AUTHOR. SAMPLE-AUTHOR.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMPLOYEE-FILE ASSIGN TO "EMPFILE.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  EMPLOYEE-FILE.
       01  EMPLOYEE-RECORD.
           05  EMP-ID              PIC 9(6).
           05  EMP-NAME            PIC X(30).
           05  EMP-SSN             PIC 9(9).
           05  EMP-DEPT            PIC X(4).
           05  EMP-SALARY          PIC 9(7)V99.
           05  EMP-HOURS-WORKED    PIC 9(3)V9.
           05  EMP-PAY-TYPE        PIC X(1).
           05  EMP-DEPENDENTS      PIC 9(2).

       WORKING-STORAGE SECTION.
       01  WS-FLAGS.
           05  WS-EOF-FLAG         PIC X VALUE "N".

       01  WS-COUNTERS.
           05  WS-EMP-COUNT        PIC 9(4) VALUE 0.
           05  WS-PROCESS-COUNT    PIC 9(4) VALUE 0.
           05  WS-ERROR-COUNT      PIC 9(4) VALUE 0.

       01  WS-PAY-FIELDS.
           05  WS-GROSS-PAY        PIC 9(7)V99 VALUE 0.
           05  WS-NET-PAY          PIC 9(7)V99 VALUE 0.
           05  WS-TAX-AMOUNT       PIC 9(7)V99 VALUE 0.
           05  WS-TAX-RATE         PIC 9V99 VALUE 0.
           05  WS-OVERTIME-PAY     PIC 9(7)V99 VALUE 0.
           05  WS-OVERTIME-HOURS   PIC 9(3)V9 VALUE 0.
           05  WS-HOURLY-RATE      PIC 9(5)V99 VALUE 0.
           05  WS-BONUS            PIC 9(5)V99 VALUE 0.
           05  WS-DEDUCTION        PIC 9(5)V99 VALUE 0.

       01  WS-TOTALS.
           05  WS-TOTAL-GROSS      PIC 9(9)V99 VALUE 0.
           05  WS-TOTAL-NET        PIC 9(9)V99 VALUE 0.
           05  WS-TOTAL-TAX        PIC 9(9)V99 VALUE 0.

       01  WS-CONSTANTS.
           05  WS-OVERTIME-FACTOR  PIC 9V9 VALUE 1.5.
           05  WS-STANDARD-HOURS   PIC 9(3) VALUE 40.
           05  WS-BONUS-THRESHOLD  PIC 9(7)V99 VALUE 5000.00.

       01  WS-REPORT-FIELDS.
           05  WS-SEPARATOR        PIC X(40)
               VALUE "----------------------------------------".
           05  WS-LOOP-IDX         PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PROGRAM.
           PERFORM INITIALIZE-PAYROLL
           PERFORM PROCESS-EMPLOYEES UNTIL WS-EOF-FLAG = "Y"
           PERFORM PRINT-SUMMARY
           STOP RUN.

       INITIALIZE-PAYROLL.
           INITIALIZE WS-COUNTERS
           INITIALIZE WS-TOTALS
           OPEN INPUT EMPLOYEE-FILE
           DISPLAY "=== PAYROLL PROCESSING STARTED ==="
           PERFORM READ-NEXT-EMPLOYEE.

       READ-NEXT-EMPLOYEE.
           READ EMPLOYEE-FILE
               AT END MOVE "Y" TO WS-EOF-FLAG.

       PROCESS-EMPLOYEES.
           ADD 1 TO WS-EMP-COUNT
           PERFORM CALCULATE-GROSS-PAY
           PERFORM DETERMINE-TAX-RATE
           PERFORM CALCULATE-DEDUCTIONS
           PERFORM CALCULATE-NET-PAY
           PERFORM PRINT-EMPLOYEE-PAY
           ADD WS-GROSS-PAY TO WS-TOTAL-GROSS
           ADD WS-NET-PAY TO WS-TOTAL-NET
           ADD WS-TAX-AMOUNT TO WS-TOTAL-TAX
           ADD 1 TO WS-PROCESS-COUNT
           PERFORM READ-NEXT-EMPLOYEE.

       CALCULATE-GROSS-PAY.
           INITIALIZE WS-PAY-FIELDS
           EVALUATE EMP-PAY-TYPE
               WHEN "S"
                   MOVE EMP-SALARY TO WS-GROSS-PAY
               WHEN "H"
                   PERFORM CALCULATE-HOURLY-PAY
               WHEN "C"
                   PERFORM CALCULATE-COMMISSION-PAY
           END-EVALUATE.

       CALCULATE-HOURLY-PAY.
           DIVIDE EMP-SALARY BY 2080
               GIVING WS-HOURLY-RATE
           IF EMP-HOURS-WORKED > WS-STANDARD-HOURS
               MULTIPLY WS-HOURLY-RATE BY WS-STANDARD-HOURS
                   GIVING WS-GROSS-PAY
               SUBTRACT WS-STANDARD-HOURS FROM
                   EMP-HOURS-WORKED
                   GIVING WS-OVERTIME-HOURS
               COMPUTE WS-OVERTIME-PAY =
                   WS-HOURLY-RATE * WS-OVERTIME-FACTOR
                   * WS-OVERTIME-HOURS
               ADD WS-OVERTIME-PAY TO WS-GROSS-PAY
           ELSE
               MULTIPLY WS-HOURLY-RATE BY EMP-HOURS-WORKED
                   GIVING WS-GROSS-PAY
           END-IF.

       CALCULATE-COMMISSION-PAY.
           MOVE EMP-SALARY TO WS-GROSS-PAY
           IF WS-GROSS-PAY > WS-BONUS-THRESHOLD
               SUBTRACT WS-BONUS-THRESHOLD FROM WS-GROSS-PAY
                   GIVING WS-BONUS
               DIVIDE WS-BONUS BY 10
                   GIVING WS-BONUS
               ADD WS-BONUS TO WS-GROSS-PAY
           END-IF.

       DETERMINE-TAX-RATE.
           EVALUATE TRUE
               WHEN WS-GROSS-PAY > 10000
                   MOVE 0.30 TO WS-TAX-RATE
               WHEN WS-GROSS-PAY > 5000
                   MOVE 0.22 TO WS-TAX-RATE
               WHEN WS-GROSS-PAY > 2000
                   MOVE 0.15 TO WS-TAX-RATE
               WHEN OTHER
                   MOVE 0.10 TO WS-TAX-RATE
           END-EVALUATE.

       CALCULATE-DEDUCTIONS.
           MULTIPLY WS-GROSS-PAY BY WS-TAX-RATE
               GIVING WS-TAX-AMOUNT
           MOVE 0 TO WS-DEDUCTION
           IF EMP-DEPENDENTS > 0
               MULTIPLY EMP-DEPENDENTS BY 50
                   GIVING WS-DEDUCTION
               IF WS-DEDUCTION > WS-TAX-AMOUNT
                   MOVE WS-TAX-AMOUNT TO WS-DEDUCTION
               END-IF
           END-IF
           SUBTRACT WS-DEDUCTION FROM WS-TAX-AMOUNT.

       CALCULATE-NET-PAY.
           SUBTRACT WS-TAX-AMOUNT FROM WS-GROSS-PAY
               GIVING WS-NET-PAY
           IF WS-NET-PAY < 0
               MOVE 0 TO WS-NET-PAY
               ADD 1 TO WS-ERROR-COUNT
               DISPLAY "WARNING: NEGATIVE NET PAY FOR "
                   EMP-NAME
           END-IF.

       PRINT-EMPLOYEE-PAY.
           DISPLAY WS-SEPARATOR
           DISPLAY "EMPLOYEE: " EMP-NAME
           DISPLAY "ID: " EMP-ID
               WITH NO ADVANCING
           DISPLAY "  DEPT: " EMP-DEPT
           DISPLAY "GROSS: " WS-GROSS-PAY
               WITH NO ADVANCING
           DISPLAY "  TAX: " WS-TAX-AMOUNT
               WITH NO ADVANCING
           DISPLAY "  NET: " WS-NET-PAY.

       PRINT-SUMMARY.
           DISPLAY " "
           DISPLAY WS-SEPARATOR
           DISPLAY "=== PAYROLL SUMMARY ==="
           DISPLAY WS-SEPARATOR
           DISPLAY "EMPLOYEES PROCESSED: " WS-PROCESS-COUNT
           DISPLAY "ERRORS FOUND:        " WS-ERROR-COUNT
           DISPLAY WS-SEPARATOR
           DISPLAY "TOTAL GROSS PAY: " WS-TOTAL-GROSS
           DISPLAY "TOTAL TAX:       " WS-TOTAL-TAX
           DISPLAY "TOTAL NET PAY:   " WS-TOTAL-NET
           DISPLAY WS-SEPARATOR
           PERFORM PRINT-FOOTER 3 TIMES
           CLOSE EMPLOYEE-FILE
           DISPLAY "=== PAYROLL PROCESSING COMPLETE ===".

       PRINT-FOOTER.
           ADD 1 TO WS-LOOP-IDX
           DISPLAY "--- END OF REPORT LINE "
               WS-LOOP-IDX " ---".
