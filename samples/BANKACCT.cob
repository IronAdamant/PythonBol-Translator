      *================================================================*
      * BANKACCT: Banking account management system
      * Inspired by github.com/ak55m/cobol-banking-system
      * Rewritten for translator testing (not a direct copy).
      * Changes: removed emoji, truncated to col 72, reformatted
      *   for fixed-format COBOL, simplified some constructs.
      * Demonstrates realistic banking COBOL including constructs
      *   that will generate TODOs (WRITE, STRING, ACCEPT, REWRITE,
      *   OPEN I-O, OPEN EXTEND).
      *================================================================*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANKACCT.
       AUTHOR. BANKING-SYSTEM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE ASSIGN TO "CUSTOMERS.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT TRANSACTION-FILE
               ASSIGN TO "TRANSACTIONS.DAT"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  CUSTOMER-FILE.
       01  CUSTOMER-RECORD.
           05  ACCT-ID            PIC X(10).
           05  ACCT-NAME          PIC X(30).
           05  ACCT-BALANCE       PIC 9(7)V99.
           05  ACCT-TYPE          PIC X(1).

       FD  TRANSACTION-FILE.
       01  TRANSACTION-RECORD.
           05  TRANS-ACCT-ID      PIC X(10).
           05  TRANS-TYPE         PIC X(1).
           05  TRANS-AMOUNT       PIC 9(7)V99.
           05  TRANS-DATE         PIC X(10).
           05  TRANS-TIME         PIC X(8).

       WORKING-STORAGE SECTION.
       01  WS-MENU-CHOICE        PIC 9 VALUE 0.
       01  WS-DONE-FLAG          PIC X VALUE "N".
       01  WS-FILE-STATUS        PIC XX VALUE "00".

       01  WS-INPUT-FIELDS.
           05  WS-ACCT-ID        PIC X(10).
           05  WS-ACCT-NAME      PIC X(30).
           05  WS-BALANCE        PIC 9(7)V99 VALUE 0.
           05  WS-ACCT-TYPE      PIC X(1).

       01  WS-SEARCH-FIELDS.
           05  WS-SEARCH-ID      PIC X(10).
           05  WS-AMOUNT         PIC 9(7)V99 VALUE 0.
           05  WS-FOUND-FLAG     PIC X VALUE "N".
           05  WS-NEW-BALANCE    PIC 9(7)V99 VALUE 0.

       01  WS-DATE-FIELDS.
           05  WS-CURRENT-DATE.
               10  WS-YEAR       PIC 9(4).
               10  WS-MONTH      PIC 9(2).
               10  WS-DAY        PIC 9(2).
           05  WS-CURRENT-TIME.
               10  WS-HOUR       PIC 9(2).
               10  WS-MINUTE     PIC 9(2).
               10  WS-SECOND     PIC 9(2).
           05  WS-DATE-STRING    PIC X(10).
           05  WS-TIME-STRING    PIC X(8).

       01  WS-COUNTERS.
           05  WS-STMT-COUNT     PIC 9(2) VALUE 0.
           05  WS-INTEREST-CT    PIC 9(4) VALUE 0.

       01  WS-INTEREST-FIELDS.
           05  WS-INTEREST-RATE  PIC 9V99 VALUE 0.02.
           05  WS-INTEREST-AMT   PIC 9(7)V99 VALUE 0.

       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "=================================="
           DISPLAY "  COBOL BANKING SYSTEM"
           DISPLAY "=================================="
           PERFORM PROCESS-MENU
               UNTIL WS-DONE-FLAG = "Y"
           STOP RUN.

       PROCESS-MENU.
           DISPLAY " "
           DISPLAY "MAIN MENU:"
           DISPLAY "  1. Create New Account"
           DISPLAY "  2. View All Accounts"
           DISPLAY "  3. Deposit Money"
           DISPLAY "  4. Withdraw Money"
           DISPLAY "  5. Mini Statement"
           DISPLAY "  6. Apply Interest (Savings)"
           DISPLAY "  7. Exit System"
           DISPLAY " "
           DISPLAY "Enter your choice (1-7): "
               WITH NO ADVANCING
           ACCEPT WS-MENU-CHOICE
           EVALUATE WS-MENU-CHOICE
               WHEN 1
                   PERFORM CREATE-ACCOUNT
               WHEN 2
                   PERFORM VIEW-ACCOUNTS
               WHEN 3
                   PERFORM DEPOSIT-MONEY
               WHEN 4
                   PERFORM WITHDRAW-MONEY
               WHEN 5
                   PERFORM MINI-STATEMENT
               WHEN 6
                   PERFORM APPLY-INTEREST
               WHEN 7
                   DISPLAY "Thank you for using the"
                   DISPLAY "Banking System. Goodbye!"
                   MOVE "Y" TO WS-DONE-FLAG
               WHEN OTHER
                   DISPLAY "Invalid option."
                   DISPLAY "Please enter 1-7."
           END-EVALUATE.

       CREATE-ACCOUNT.
           DISPLAY " "
           DISPLAY "CREATE NEW ACCOUNT"
           DISPLAY "=================="
           DISPLAY "Enter Account ID: "
               WITH NO ADVANCING
           ACCEPT WS-ACCT-ID
           DISPLAY "Enter Customer Name: "
               WITH NO ADVANCING
           ACCEPT WS-ACCT-NAME
           DISPLAY "Enter Initial Balance: "
               WITH NO ADVANCING
           ACCEPT WS-BALANCE
           DISPLAY "Account Type (S/C): "
               WITH NO ADVANCING
           ACCEPT WS-ACCT-TYPE
           PERFORM WRITE-CUSTOMER-RECORD
           DISPLAY " "
           DISPLAY "Account created successfully!"
           DISPLAY "  Account ID: " WS-ACCT-ID
           DISPLAY "  Name:       " WS-ACCT-NAME
           DISPLAY "  Balance:    " WS-BALANCE
           DISPLAY "  Type:       " WS-ACCT-TYPE.

       VIEW-ACCOUNTS.
           DISPLAY " "
           DISPLAY "ALL CUSTOMER ACCOUNTS"
           DISPLAY "====================="
           MOVE "00" TO WS-FILE-STATUS
           OPEN INPUT CUSTOMER-FILE
           IF WS-FILE-STATUS NOT = "00"
               DISPLAY "Error opening file: "
                   WS-FILE-STATUS
           ELSE
               DISPLAY "ID         | Name"
                   "                 | Balance"
               DISPLAY "-----------|------"
                   "-----------------|-------"
               PERFORM READ-ALL-CUSTOMERS
                   UNTIL WS-FILE-STATUS = "10"
           END-IF
           CLOSE CUSTOMER-FILE.

       READ-ALL-CUSTOMERS.
           READ CUSTOMER-FILE
               AT END MOVE "10" TO WS-FILE-STATUS
           IF WS-FILE-STATUS = "00"
               DISPLAY ACCT-ID " | "
                   ACCT-NAME " | $"
                   ACCT-BALANCE " | "
                   ACCT-TYPE
           END-IF.

       DEPOSIT-MONEY.
           DISPLAY " "
           DISPLAY "DEPOSIT MONEY"
           DISPLAY "============="
           DISPLAY "Enter Account ID: "
               WITH NO ADVANCING
           ACCEPT WS-SEARCH-ID
           DISPLAY "Enter deposit amount: "
               WITH NO ADVANCING
           ACCEPT WS-AMOUNT
           PERFORM UPDATE-BALANCE-ADD
           IF WS-FOUND-FLAG = "Y"
               DISPLAY " "
               DISPLAY "Deposit successful!"
               DISPLAY "  Account: " WS-SEARCH-ID
               DISPLAY "  Amount:  $" WS-AMOUNT
               DISPLAY "  New Bal: $"
                   WS-NEW-BALANCE
           ELSE
               DISPLAY " "
               DISPLAY "Account not found: "
                   WS-SEARCH-ID
           END-IF.

       WITHDRAW-MONEY.
           DISPLAY " "
           DISPLAY "WITHDRAW MONEY"
           DISPLAY "=============="
           DISPLAY "Enter Account ID: "
               WITH NO ADVANCING
           ACCEPT WS-SEARCH-ID
           DISPLAY "Enter withdrawal amount: "
               WITH NO ADVANCING
           ACCEPT WS-AMOUNT
           PERFORM UPDATE-BALANCE-SUBTRACT
           IF WS-FOUND-FLAG = "Y"
               DISPLAY " "
               DISPLAY "Withdrawal successful!"
               DISPLAY "  Account: " WS-SEARCH-ID
               DISPLAY "  Amount:  $" WS-AMOUNT
               DISPLAY "  New Bal: $"
                   WS-NEW-BALANCE
           ELSE
               DISPLAY " "
               DISPLAY "Account not found: "
                   WS-SEARCH-ID
           END-IF.

       UPDATE-BALANCE-ADD.
           MOVE "N" TO WS-FOUND-FLAG
           MOVE "00" TO WS-FILE-STATUS
           OPEN I-O CUSTOMER-FILE
           IF WS-FILE-STATUS NOT = "00"
               DISPLAY "Error opening file: "
                   WS-FILE-STATUS
           ELSE
               PERFORM SEARCH-AND-DEPOSIT
                   UNTIL WS-FILE-STATUS = "10"
           END-IF
           CLOSE CUSTOMER-FILE.

       SEARCH-AND-DEPOSIT.
           READ CUSTOMER-FILE
               AT END MOVE "10" TO WS-FILE-STATUS
           IF WS-FILE-STATUS = "00"
               IF ACCT-ID = WS-SEARCH-ID
                   ADD WS-AMOUNT TO ACCT-BALANCE
                   MOVE ACCT-BALANCE
                       TO WS-NEW-BALANCE
                   REWRITE CUSTOMER-RECORD
                   MOVE "Y" TO WS-FOUND-FLAG
                   PERFORM LOG-TRANSACTION-DEPOSIT
                   MOVE "10" TO WS-FILE-STATUS
               END-IF
           END-IF.

       UPDATE-BALANCE-SUBTRACT.
           MOVE "N" TO WS-FOUND-FLAG
           MOVE "00" TO WS-FILE-STATUS
           OPEN I-O CUSTOMER-FILE
           IF WS-FILE-STATUS NOT = "00"
               DISPLAY "Error opening file: "
                   WS-FILE-STATUS
           ELSE
               PERFORM SEARCH-AND-WITHDRAW
                   UNTIL WS-FILE-STATUS = "10"
           END-IF
           CLOSE CUSTOMER-FILE.

       SEARCH-AND-WITHDRAW.
           READ CUSTOMER-FILE
               AT END MOVE "10" TO WS-FILE-STATUS
           IF WS-FILE-STATUS = "00"
               IF ACCT-ID = WS-SEARCH-ID
                   IF ACCT-BALANCE >= WS-AMOUNT
                       SUBTRACT WS-AMOUNT
                           FROM ACCT-BALANCE
                       MOVE ACCT-BALANCE
                           TO WS-NEW-BALANCE
                       REWRITE CUSTOMER-RECORD
                       MOVE "Y" TO WS-FOUND-FLAG
                       PERFORM LOG-TRANSACTION-WITHDRAW
                   ELSE
                       DISPLAY " "
                       DISPLAY "Insufficient funds!"
                       DISPLAY "  Balance: $"
                           ACCT-BALANCE
                       DISPLAY "  Requested: $"
                           WS-AMOUNT
                       MOVE "N" TO WS-FOUND-FLAG
                   END-IF
                   MOVE "10" TO WS-FILE-STATUS
               END-IF
           END-IF.

       WRITE-CUSTOMER-RECORD.
           MOVE "00" TO WS-FILE-STATUS
           OPEN EXTEND CUSTOMER-FILE
           IF WS-FILE-STATUS NOT = "00"
               DISPLAY "Error opening file: "
                   WS-FILE-STATUS
           ELSE
               MOVE WS-ACCT-ID TO ACCT-ID
               MOVE WS-ACCT-NAME TO ACCT-NAME
               MOVE WS-BALANCE TO ACCT-BALANCE
               MOVE WS-ACCT-TYPE TO ACCT-TYPE
               WRITE CUSTOMER-RECORD
               IF WS-FILE-STATUS NOT = "00"
                   DISPLAY "Error writing: "
                       WS-FILE-STATUS
               END-IF
           END-IF
           CLOSE CUSTOMER-FILE.

       MINI-STATEMENT.
           DISPLAY " "
           DISPLAY "MINI STATEMENT"
           DISPLAY "=============="
           DISPLAY "Enter Account ID: "
               WITH NO ADVANCING
           ACCEPT WS-SEARCH-ID
           DISPLAY " "
           DISPLAY "Last 5 transactions for: "
               WS-SEARCH-ID
           DISPLAY "Date       | Time     |"
               " Type | Amount"
           DISPLAY "-----------|----------|"
               "------|-------"
           MOVE 0 TO WS-STMT-COUNT
           MOVE "00" TO WS-FILE-STATUS
           OPEN INPUT TRANSACTION-FILE
           IF WS-FILE-STATUS NOT = "00"
               DISPLAY "No transaction history."
           ELSE
               PERFORM READ-TRANSACTIONS
                   UNTIL WS-FILE-STATUS = "10"
                   OR WS-STMT-COUNT >= 5
               IF WS-STMT-COUNT = 0
                   DISPLAY "No transactions found."
               END-IF
           END-IF
           CLOSE TRANSACTION-FILE.

       READ-TRANSACTIONS.
           READ TRANSACTION-FILE
               AT END MOVE "10" TO WS-FILE-STATUS
           IF WS-FILE-STATUS = "00"
               IF TRANS-ACCT-ID = WS-SEARCH-ID
                   ADD 1 TO WS-STMT-COUNT
                   IF TRANS-TYPE = "D"
                       DISPLAY TRANS-DATE " | "
                           TRANS-TIME " | DEP  | $"
                           TRANS-AMOUNT
                   ELSE
                       DISPLAY TRANS-DATE " | "
                           TRANS-TIME " | WTH  | $"
                           TRANS-AMOUNT
                   END-IF
               END-IF
           END-IF.

       APPLY-INTEREST.
           DISPLAY " "
           DISPLAY "APPLY INTEREST TO SAVINGS"
           DISPLAY "========================="
           DISPLAY "Applying 2% annual interest"
           MOVE 0 TO WS-INTEREST-CT
           MOVE "00" TO WS-FILE-STATUS
           OPEN I-O CUSTOMER-FILE
           IF WS-FILE-STATUS NOT = "00"
               DISPLAY "Error opening file: "
                   WS-FILE-STATUS
           ELSE
               PERFORM APPLY-INTEREST-LOOP
                   UNTIL WS-FILE-STATUS = "10"
               DISPLAY " "
               DISPLAY "Interest applied to "
                   WS-INTEREST-CT
                   " savings accounts."
           END-IF
           CLOSE CUSTOMER-FILE.

       APPLY-INTEREST-LOOP.
           READ CUSTOMER-FILE
               AT END MOVE "10" TO WS-FILE-STATUS
           IF WS-FILE-STATUS = "00"
               IF ACCT-TYPE = "S"
                   COMPUTE WS-INTEREST-AMT =
                       ACCT-BALANCE * WS-INTEREST-RATE
                   ADD WS-INTEREST-AMT
                       TO ACCT-BALANCE
                   REWRITE CUSTOMER-RECORD
                   ADD 1 TO WS-INTEREST-CT
                   MOVE ACCT-ID TO WS-SEARCH-ID
                   PERFORM LOG-TRANSACTION-INTEREST
                   DISPLAY "Interest on "
                       ACCT-ID ": $"
                       WS-INTEREST-AMT
               END-IF
           END-IF.

       LOG-TRANSACTION-DEPOSIT.
           PERFORM GET-CURRENT-DATETIME
           MOVE "00" TO WS-FILE-STATUS
           OPEN EXTEND TRANSACTION-FILE
           MOVE WS-SEARCH-ID TO TRANS-ACCT-ID
           MOVE "D" TO TRANS-TYPE
           MOVE WS-AMOUNT TO TRANS-AMOUNT
           MOVE WS-DATE-STRING TO TRANS-DATE
           MOVE WS-TIME-STRING TO TRANS-TIME
           WRITE TRANSACTION-RECORD
           CLOSE TRANSACTION-FILE.

       LOG-TRANSACTION-WITHDRAW.
           PERFORM GET-CURRENT-DATETIME
           MOVE "00" TO WS-FILE-STATUS
           OPEN EXTEND TRANSACTION-FILE
           MOVE WS-SEARCH-ID TO TRANS-ACCT-ID
           MOVE "W" TO TRANS-TYPE
           MOVE WS-AMOUNT TO TRANS-AMOUNT
           MOVE WS-DATE-STRING TO TRANS-DATE
           MOVE WS-TIME-STRING TO TRANS-TIME
           WRITE TRANSACTION-RECORD
           CLOSE TRANSACTION-FILE.

       LOG-TRANSACTION-INTEREST.
           PERFORM GET-CURRENT-DATETIME
           MOVE "00" TO WS-FILE-STATUS
           OPEN EXTEND TRANSACTION-FILE
           MOVE WS-SEARCH-ID TO TRANS-ACCT-ID
           MOVE "I" TO TRANS-TYPE
           MOVE WS-INTEREST-AMT TO TRANS-AMOUNT
           MOVE WS-DATE-STRING TO TRANS-DATE
           MOVE WS-TIME-STRING TO TRANS-TIME
           WRITE TRANSACTION-RECORD
           CLOSE TRANSACTION-FILE.

       GET-CURRENT-DATETIME.
           ACCEPT WS-CURRENT-DATE FROM DATE
           ACCEPT WS-CURRENT-TIME FROM TIME
           STRING WS-YEAR "/" WS-MONTH "/"
               WS-DAY DELIMITED BY SIZE
               INTO WS-DATE-STRING
           STRING WS-HOUR ":" WS-MINUTE ":"
               WS-SECOND DELIMITED BY SIZE
               INTO WS-TIME-STRING.
