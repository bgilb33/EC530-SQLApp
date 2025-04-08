import pandas as pd
import sqlite3
import openai
import os
from dotenv import load_dotenv
load_dotenv()

def map_dtype_to_sql(dtype):
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    elif pd.api.types.is_float_dtype(dtype):
        return "REAL"
    else:
        return "TEXT"

def log_error(message):
    with open("error_log.txt", "a") as f:
        f.write(f"{message}\n")

def handle_existing_table(cursor, table_name):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
    if cursor.fetchone():
        print(f"\nTable '{table_name}' already exists.")
        choice = input("Choose an option — (o)verwrite, (r)ename, or (s)kip: ").strip().lower()

        if choice == 'o':
            cursor.execute(f'DROP TABLE IF EXISTS "{table_name}";')
            print(f"Table '{table_name}' overwritten.")
            return table_name

        elif choice == 'r':
            new_name = input("Enter new table name: ").strip()
            print(f"Table will be created as '{new_name}' instead.")
            return new_name

        elif choice == 's':
            print("Skipping table creation.")
            return None

        else:
            log_error(f"Invalid option selected for existing table '{table_name}'.")
            return None
    return table_name

def create_table_from_csv(csv_file, db_name, table_name):
    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        log_error(f"Error reading CSV '{csv_file}': {str(e)}")
        print(f"Failed to read CSV: {e}")
        return

    columns = df.columns
    types = [map_dtype_to_sql(df[col].dtype) for col in columns]

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    table_name = handle_existing_table(cursor, table_name)
    if not table_name:
        conn.close()
        return

    columns_sql = ", ".join([f'"{col}" {typ}' for col, typ in zip(columns, types)])
    create_stmt = f'CREATE TABLE "{table_name}" ({columns_sql});'

    try:
        cursor.execute(create_stmt)
        conn.commit()
        df.to_sql(table_name, conn, if_exists="append", index=False)
        print(f"\nTable '{table_name}' created and populated with data from {csv_file}")
        rows = cursor.execute(f"SELECT * FROM {table_name} LIMIT 5").fetchall()
        for row in rows:
            print(row)
    except Exception as e:
        log_error(f"Error creating or populating table '{table_name}': {str(e)}")
        print(f"Error: {e}")
    finally:
        conn.close()

def list_tables(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("\nAvailable Tables:")
    for table in tables:
        print(f" - {table[0]}")

def ask_llm_for_sql(user_question, schema_description):
    prompt = f"""
You are an AI assistant tasked with converting user queries into SQL statements.
The database uses SQLite and contains the following tables and columns:

{schema_description}

User Query: "{user_question}"

Your task:
1. Generate a SQL query that answers the user's question.
2. Ensure it's valid SQLite syntax.
3. Return only the SQL query — no extra explanations.
    """

    openai.api_key = os.getenv("OPENAI_API_KEY")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{ "role": "user", "content": prompt }],
            temperature=0,
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        log_error(f"OpenAI API error: {e}")
        print("LLM failed to respond.")
        return None

def interactive_mode(db_name):
    print("\nLLM Spreadsheet Assistant (CLI Mode)")
    print("Type 'help' to see options.\n")

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    while True:
        user_input = input(">>> ").strip()

        if user_input.lower() == "help":
            print("""
Commands:
- load <csv_file> <table_name> : Load CSV into database
- query <SQL>                  : Run an SQL query
- tables                       : List all tables
- ask <natural language>       : Ask a question in plain English
- exit                         : Exit the program
""")
        elif user_input.lower().startswith("load "):
            try:
                parts = user_input.split()
                csv_file = parts[1]
                table_name = parts[2]
                create_table_from_csv(csv_file, db_name, table_name)
            except Exception as e:
                log_error(f"Error in load command: {str(e)}")
                print("Usage: load <csv_file> <table_name>")
        elif user_input.lower().startswith("query "):
            sql = user_input[6:].strip()
            try:
                rows = cursor.execute(sql).fetchall()
                for row in rows:
                    print(row)
            except Exception as e:
                log_error(f"Query error: {str(e)}")
                print(f"Query failed: {e}")
        elif user_input.lower() == "tables":
            list_tables(cursor)
        elif user_input.lower().startswith("ask "):
            question = user_input[4:].strip()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [t[0] for t in cursor.fetchall()]
            schema_description = ""
            for table in tables:
                cursor.execute(f"PRAGMA table_info({table});")
                cols = cursor.fetchall()
                col_list = ", ".join([col[1] for col in cols])
                schema_description += f"- {table} ({col_list})\n"

            sql = ask_llm_for_sql(question, schema_description)

            if sql:
                print(f"\nGenerated SQL:\n{sql}\n")
                try:
                    rows = cursor.execute(sql).fetchall()
                    for row in rows:
                        print(row)
                except Exception as e:
                    log_error(f"Failed to execute generated SQL: {e}")
                    print("Generated SQL was invalid.")
        elif user_input.lower() == "exit":
            print("Exiting.")
            break
        else:
            print("Unknown command. Type 'help' for options.")

    conn.close()

if __name__ == "__main__":
    interactive_mode("my_database.db")
