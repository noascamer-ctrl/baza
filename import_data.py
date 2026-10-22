import sqlite3
import os

# ზუსტად ეს მისამართი მივუთითოთ
txt_file = r"C:\license-site\2012.txt"
db_file = r"C:\license-site\database.db"

print("ვიწყებ 2012.txt ფაილის დამუშავებას...")
print(f"ვეძებ ფაილს აქ: {txt_file}")

if not os.path.exists(txt_file):
    print("❌ ფაილი ვერ მოიძებნა! გთხოვ დარწმუნდი რომ ზუსტად ასე ჰქვია: 2012.txt")
    # თუ ვერ იპოვა, ვცადოთ ვიპოვოთ ის საქაღალდეში
    for f in os.listdir(r"C:\license-site"):
        if "2012" in f:
            print(f"⚠️ მაგრამ ვიპოვე ეს ფაილი: {f}")
    exit()

if os.path.exists(db_file):
    os.remove(db_file)

conn = sqlite3.connect(db_file)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT)''')

with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
    count = 0
    for line in f:
        line = line.strip()
        if line:
            c.execute("INSERT INTO records (data) VALUES (?)", (line,))
            count += 1
    conn.commit()
    print(f"✅ წარმატებით გადავიდა {count} ხაზი ბაზაში!")

conn.close()
print("დასრულდა. ახლა გაუშვი: python app.py")