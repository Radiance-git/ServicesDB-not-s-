import pandas as pd
import pyodbc
import requests
import time

csv_file = "data.csv"
df = pd.read_csv(csv_file)
# clean data
df["name_of_site"] = df["name_of_site"].astype(str).str.strip()
df["url"] = df["url"].astype(str).str.strip()
df["org_code"] = df["org_code"].astype(str).str.strip()
df = df[df["url"].notna() & df["org_code"].notna()]

print(f"Total rows in CSV: {len(df)}")

print("Connecting to database...")
conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"        
    "DATABASE=services;"  
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()
print("Connected successfully.")

try:
    #   base seeding(statusTypes)
    check_status = "SELECT COUNT(1) FROM [dbo].[StatusTypes] WHERE [StatusID] = ?"
    cursor.execute("SET IDENTITY_INSERT [dbo].[StatusTypes] ON;")
    
    cursor.execute(check_status, 0)
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO [dbo].[StatusTypes] ([StatusID], [Title], [Description]) VALUES (0, N'غیر فعال', N'خطا در برقراری ارتباط')")
    
    cursor.execute(check_status, 1)
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO [dbo].[StatusTypes] ([StatusID], [Title], [Description]) VALUES (1, N'فعال', N'بدون خطا')")
        
    cursor.execute("SET IDENTITY_INSERT [dbo].[StatusTypes] OFF;")
    
    # Setup Evaluatorrrrr
    bot_name = "the bot"
    cursor.execute("SELECT [EvaluatorID] FROM [dbo].[Evaluators] WHERE [Name] = ?", bot_name)
    bot_row = cursor.fetchone()
    
    if bot_row is None:
        cursor.execute("""
            INSERT INTO [dbo].[Evaluators] ([Name], [Type], [Description], [IsActive], [CreatedDate])
            OUTPUT INSERTED.EvaluatorID
            VALUES (?, 1, N'ربات مانیتورینگ خودکار', 1, GETDATE())
        """, bot_name)
        evaluator_id = int(cursor.fetchone()[0])
        print(f"Evaluator created with ID: {evaluator_id}")
    else:
        evaluator_id = int(bot_row[0])
        print(f"Evaluator existing ID: {evaluator_id}")

    # 3. Import Data
    ins_org = """
    SET NOCOUNT ON;
    INSERT INTO [dbo].[Organizations] ([Name], [Type], [CreatedDate]) VALUES (?, 1, GETDATE());
    SELECT SCOPE_IDENTITY();
    """
    
    ins_svc = """
    INSERT INTO [dbo].[Services] ([Name], [OrganizationID], [ContactID], [Url], [IsActive], [CreateDate], [Description])
    VALUES (?, ?, NULL, ?, 1, GETDATE(), NULL);
    """
    
    print("Importing orgs and services...")
    count = 0
    for _, row in df.iterrows():
        cursor.execute(ins_org, row["org_code"])
        org_id = int(cursor.fetchone()[0]) 
        
        cursor.execute(ins_svc, row["name_of_site"], org_id, row["url"])
        count += 1
    
    conn.commit()
    print(f"Imported {count} rows successfully.")

    # 4. Monitoring Pipeline
    print("\nStarting monitoring process...")
    cursor.execute("SELECT [ServiceID], [Url] FROM [dbo].[Services]")
    services = cursor.fetchall()
    total_svcs = len(services)
    
    ins_eval = """
    INSERT INTO [dbo].[Evaluations] 
    ([ServiceID], [EvaluatorID], [EvaluationDate], [ResponseTime], [StatusID], [Description], [CreatedDate])
    VALUES (?, ?, GETDATE(), ?, ?, ?, GETDATE())
    """
    
    upd_svc = "UPDATE [dbo].[Services] SET [IsActive] = ? WHERE [ServiceID] = ?"
    
    idx = 0
    for svc in services:
        s_id = svc.ServiceID
        url = svc.Url
        res_time = 0
        desc = "Auto checked."
        
        try:
            t0 = time.time()
            r = requests.get(url, timeout=8)
            res_time = int(r.elapsed.total_seconds() * 1000) 
            
            if r.status_code < 500:
                status = 1
                desc += f" Status code: {r.status_code}"
            else:
                status = 0
                desc += f" HTTP error: {r.status_code}"
        except Exception as err:
            status = 0
            res_time = 0
            desc += " Connection failed or timeout."
            
        cursor.execute(ins_eval, s_id, evaluator_id, res_time, status, desc)
        cursor.execute(upd_svc, status, s_id)
        
        idx += 1
        print(f"Progress: {idx}/{total_svcs} | ServiceID: {s_id} | Status: {status} | {res_time}ms")

    conn.commit()
    print("\nDone..bye bye")

except Exception as e:
    conn.rollback()
    print("Error occurred, rollback executed:", e)

finally:
    cursor.close()
    conn.close()