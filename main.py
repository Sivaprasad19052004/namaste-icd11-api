# main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian, SecondaryCaptureImageStorage
import io, os, json, datetime

DATA_DIR = "/tmp/data"   # Render provides ephemeral disk; for prototype this is OK
DICOM_DIR = os.path.join(DATA_DIR, "dicom")
os.makedirs(DICOM_DIR, exist_ok=True)

# load mappings.json that we'll create next
with open("mappings.json", "r", encoding="utf8") as f:
    MAPPINGS = json.load(f)

app = FastAPI(title="Namaste-ICD11 TM2 microservice - prototype")

def lookup_disease(term: str):
    term_l = term.strip().lower()
    for cid, entry in MAPPINGS.items():
        fields = [entry.get(k,"").lower() for k in ("allopathy","ayurveda","unani","siddha")]
        synonyms = [s.lower() for s in entry.get("synonyms",[])]
        if term_l in fields + synonyms:
            return {"common_id": cid, **entry}
    # fallback: exact substring search
    for cid, entry in MAPPINGS.items():
        allnames = " ".join([entry.get(k,"") for k in ("allopathy","ayurveda","unani","siddha")] + entry.get("synonyms",[])).lower()
        if term_l in allnames:
            return {"common_id": cid, **entry}
    return None

@app.post("/disease/lookup")
async def disease_lookup(name: str = Form(...)):
    res = lookup_disease(name)
    if not res:
        return JSONResponse(status_code=404, content={"message": "Not found"})
    return res

@app.post("/image/upload")
async def upload_image(
    image: UploadFile = File(...),
    patient_id: str = Form(...),
    patient_name: str = Form(...),
    study_desc: str = Form("Clinical Photo"),
    condition_name: str = Form(None)
):
    # read image into memory and convert to RGB
    data = await image.read()
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid image")
    rows, cols = im.size[1], im.size[0]
    pixel_bytes = im.tobytes()

    # DICOM metadata
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.Modality = "OT"  # Other
    ds.ContentDate = datetime.datetime.now().strftime("%Y%m%d")
    ds.ContentTime = datetime.datetime.now().strftime("%H%M%S")
    ds.Rows = rows
    ds.Columns = cols
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixel_bytes

    # Save on disk
    filename = f"{patient_id}_{generate_uid()}.dcm"
    dicom_path = os.path.join(DICOM_DIR, filename)
    ds.save_as(dicom_path)

    mapping = lookup_disease(condition_name) if condition_name else None
    return {"message":"saved", "dicom_path": dicom_path, "mapping": mapping}

