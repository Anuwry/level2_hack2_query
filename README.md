# CCTV Log Query Mock

```text
D:\sup_ai\query_mock\cctv_vehicle_log_routed.csv
```

## ใช้งานเร็ว

รันจากโฟลเดอร์โปรเจค:

```powershell
cd D:\sup_ai\query_mock
python -m cctv_query --question "กล้อง CCTV04 ช่วง 1:05:00-1:15:00 มีรถวิ่งผ่านกี่คัน ยี่ห้อและสีอะไรบ้าง"
```

รันเว็บ local:

```powershell
cd D:\sup_ai\query_mock
python -m cctv_query.web --host 127.0.0.1 --port 8765
```

เปิดเว็บ:

```text
http://127.0.0.1:8765
```

ถ้าต้องการระบุไฟล์เอง:

```powershell
python -m cctv_query --csv D:\sup_ai\query_mock\cctv_vehicle_log_routed.csv --question "วันที่ 12-05-2026 กล้อง CCTV07 มีรถสีแดงผ่านกี่คัน"
```

โหมดถามตอบต่อเนื่อง:

```powershell
python -m cctv_query
```

JSON output:

```powershell
python -m cctv_query --json --question "CCTV07 on 2026-05-12 red cars"
```

ถาม route/ลำดับกล้องที่เดินทาง:

```powershell
python -m cctv_query --question "วันที่ 12 รถ Toyota ช่วง 22:00-23:00 เดินทางไปทางไหนบ้าง"
```

ถามรายการรถไม่ซ้ำ:

```powershell
python -m cctv_query --question "วันที่ 12 รถคันไหนวิ่งผ่านบ้างไม่ซ้ำกัน"
```

## รองรับเงื่อนไข

- วันที่ เช่น `12-05-2026`, `2026-05-12` หรือแบบย่อ `วันที่ 12` ถ้าใน CSV มีวันที่นั้นไม่กำกวม
- กล้อง เช่น `CCTV04`, `CCTV4`, `กล้อง 4`, `กล้องตัวที่ 1`
- ช่วงเวลา เช่น `1:05:00-1:15:00`, `between 08:00 and 10:00`
- ประเภทรถ เช่น `Car`, `Motorcycle`, `Bus`, `Truck`, `รถส่วนบุคคล`, `มอเตอร์ไซค์`, `รถบรรทุก`
- สี เช่น `สีแดง`, `red`, `blue`; ระบบเทียบสีแบบ exact เท่านั้น เช่น `Red` ไม่เท่ากับ `Red-White` และ `Green` ไม่เท่ากับ `Metallic Green`
- หลายสีในคำถามเดียว เช่น `Red and Red-White` จะนับแบบ OR เฉพาะสองสีนั้น ไม่ดึง `White` จากชื่อ `Red-White` มาปน
- ยี่ห้อจากค่าที่พบใน CSV เช่น `Toyota`, `Honda`, `Mercedes-Benz`; ชื่อแบบย่อที่เป็นส่วนของยี่ห้อก็ใช้ได้ถ้าไม่กำกวม เช่น `Benz` จะ match `Mercedes-Benz`
- คำถาม route เช่น `เดินทางไปทางไหน`, `เส้นทาง`, `route`, `direction` โดยตอบเป็นลำดับกล้องที่ผ่าน
- คำถามรายการรถ เช่น `รถคันไหน`, `รถอะไรบ้าง`, `รายการรถ`, `which vehicles` โดยตอบเป็นรายการรถไม่ซ้ำพร้อมเวลาและกล้องที่ผ่าน
- ถ้าระบุวันที่หรือกล้องที่ไม่มีอยู่ใน CSV เช่น `วันที่ 14` หรือ `CCTV99` ระบบจะตอบ `Question Out Of Range`

## การนับจำนวนรถ

ระบบนับเป็นจำนวนรถไม่ซ้ำ ไม่ใช่จำนวนแถวใน CSV โดยจัดกลุ่มแถวที่มี `Date + Brand + Color + Type` เดียวกันและเวลาใกล้กันภายใน 30 นาทีเป็นรถคันเดียวกัน เช่น Toyota สีแดง วันที่ 12 ที่ผ่านหลายกล้องจะตอบเป็น `1 คัน` และบอกจำนวน detection เพิ่ม เช่น `ตรวจพบ 4 ครั้ง`

ถ้าคำถามระบุว่า `รถไม่ซ้ำ`, `ไม่ซ้ำกัน`, `unique vehicles` หรือ `distinct vehicles` ระบบจะนับแบบ distinct identity ด้วย `Date + Brand + Color + Type` โดยไม่แยกซ้ำตามช่วงเวลา เช่น truck วันที่ 12 จะตอบ `21 คันไม่ซ้ำ` และบอกเพิ่มว่า `รวมซ้ำ 23 รายการ, ตรวจพบ 49 ครั้ง`

## การตอบ route

ระบบสรุป route จากลำดับเวลาใน CSV เช่น `CCTV09 -> CCTV08 -> CCTV07 -> CCTV04` พร้อมเวลาเริ่ม-จบของ detection ชุดนั้น ถ้าถามด้วยเงื่อนไขกล้อง เช่น `ผ่าน CCTV07 ไปทางไหน` ระบบจะหา route ของรถที่มี detection ผ่านกล้องนั้น แล้วแสดงลำดับกล้องทั้งหมดใน route

หมายเหตุ: CSV ไม่มีคอลัมน์ทิศทางเข้า/ออกหรือตำแหน่งจริงของกล้อง ดังนั้นระบบยังไม่สามารถบอกทิศทางภูมิศาสตร์แบบ `เหนือ/ใต้/เข้าซอย/ออกถนน` ได้โดยตรง คำว่า `วิ่งออก` จะถูกใช้เป็นคำบรรยายเหตุการณ์ แต่ไม่ได้กรองทิศทาง

## ทดสอบ

```powershell
python -m unittest discover -s tests
```

## Optional LLM normalizer: Qwen3.5-4B

The rule-based parser still works by default. To handle unusual wording first, enable the optional LLM normalizer. It sends an OpenAI-compatible Chat Completions request with a `normalize_cctv_query` tool schema, then converts the tool arguments into a canonical question for the existing parser.

Default model:

```text
Qwen/Qwen3.5-4B
```

Environment variables:

```powershell
$env:CCTV_LLM_ENABLED="1"
$env:CCTV_LLM_BASE_URL="http://127.0.0.1:8080/v1"
$env:CCTV_LLM_MODEL="Qwen/Qwen3.5-4B"
$env:CCTV_LLM_MODE="auto"
$env:CCTV_LLM_TIMEOUT_SECONDS="8"
```

`CCTV_LLM_MODE=auto` tries tool calling first and falls back to JSON-only normalization if the endpoint rejects `tools`. Use `tools` to force tool calling only, or `json` for JSON-only mode.

Run with CLI:

```powershell
python -m cctv_query --llm --question "กล้องหนึ่ง รถส่วนตัว สีแดง วันที่สิบสอง มีคันไหนบ้าง"
```

Run with web:

```powershell
python -m cctv_query.web --host 127.0.0.1 --port 8765
```

## CSV questions and export

หน้าเว็บรองรับการวางหรืออัปโหลด CSV คำถาม แล้ว export คำตอบเป็น CSV ได้ โดยใช้คอลัมน์:

```csv
Question ID,CCTV ID,Time Range,Query
Q1,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี
Q2,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อ
Q3,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามสี
```

ระบบจะ normalize `CCTVO1` เป็น `CCTV01` และเวลาแบบ `0.01.00` เป็น `00:01:00` ก่อน query จากนั้นแสดงทั้งคำตอบอ่านง่ายและ CSV answers:

```csv
Question ID,Answer
Q1,"[(Toyota, Gray):1, ...]"
Q2,"[Toyota:2, ...]"
Q3,"[Gray:5, ...]"
```

ในหน้าเว็บใช้ปุ่ม `Run CSV` เพื่อประมวลผล และ `Export answers CSV` เพื่อดาวน์โหลดไฟล์คำตอบ

หมายเหตุ: คำถามเดี่ยวในช่อง `คำถาม` ก็จะแสดงผลใน tab `CSV` และกด `Export answers CSV` ได้เหมือนกัน โดยใช้ `Question ID` เป็น `Q1` อัตโนมัติ

Local llama.cpp example, using a GGUF quantization compatible with Qwen/Qwen3.5-4B:

```powershell
llama-server -hf <GGUF_REPO_FOR_QWEN3.5_4B>:Q4_K_M -a Qwen/Qwen3.5-4B --host 127.0.0.1 --port 8080
```

Online/OpenAI-compatible endpoint example:

```powershell
$env:CCTV_LLM_ENABLED="1"
$env:CCTV_LLM_BASE_URL="https://your-provider.example/v1"
$env:CCTV_LLM_API_KEY="your-api-key"
$env:CCTV_LLM_MODEL="Qwen/Qwen3.5-4B"
```
