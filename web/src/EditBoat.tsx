import { FormEvent, useState } from "react";
import { api, ApiError, Boat, photoUrl } from "./api";
import { Modal } from "./Modal";
import { PictureError, toUploadJpeg } from "./photo";
import { zones } from "./zones";

/** Changing a boat's name, port, description and time zone. A boat's owners may; so may the administrator. */
export function EditBoat({ boat, onClose, onSaved, onPhotoChanged }: { boat: Boat; onClose: () => void; onSaved: () => void; onPhotoChanged: () => void }) {
  const [name, setName] = useState(boat.name);
  const [port, setPort] = useState(boat.home_port);
  const [description, setDescription] = useState(boat.description);
  const [timezone, setTimezone] = useState(boat.timezone);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [photo, setPhoto] = useState(boat.photo);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState("");

  async function choosePhoto(file: File | undefined) {
    if (!file) return;
    setPhotoBusy(true);
    setPhotoError("");
    try {
      setPhoto(await api.uploadPhoto(boat.id, await toUploadJpeg(file)));
      onPhotoChanged();
    } catch (err) {
      setPhotoError(err instanceof PictureError || err instanceof ApiError ? err.message : "something went wrong");
    }
    setPhotoBusy(false);
  }

  async function removePhoto() {
    setPhotoBusy(true);
    setPhotoError("");
    try {
      await api.deletePhoto(boat.id);
      setPhoto(null);
      onPhotoChanged();
    } catch (err) {
      setPhotoError(err instanceof ApiError ? err.message : "something went wrong");
    }
    setPhotoBusy(false);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.editBoat(boat.id, { name, home_port: port, description, timezone });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "something went wrong");
      setBusy(false);
    }
  }

  return (
    <Modal title="Edit boat" onClose={onClose}>
      <div className="photo-edit">
        <strong>Photo</strong>
        {photo ? <img src={photoUrl(boat.id, photo)} alt={`Photo of ${boat.name}`} className="photo-preview" /> : <p className="hint">No photo yet. A picture helps people recognise the boat.</p>}
        <div className="photo-actions">
          <label className="button secondary file-button">
            {photoBusy ? "Working…" : photo ? "Choose a different photo" : "Choose a photo"}
            <input type="file" accept="image/jpeg,image/png,image/webp" disabled={photoBusy} onChange={(e) => { void choosePhoto(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          {photo && (
            <button type="button" className="link-button" disabled={photoBusy} onClick={removePhoto}>
              Remove photo
            </button>
          )}
        </div>
        {photoError && (
          <p className="error" role="alert">
            {photoError}
          </p>
        )}
      </div>
      <form onSubmit={submit} className="form">
        <label>
          Boat name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required autoFocus />
        </label>
        <label>
          Home port
          <input value={port} onChange={(e) => setPort(e.target.value)} maxLength={80} required />
        </label>
        <label>
          About the boat <span className="hint">(optional)</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={4} />
        </label>
        <label>
          Time zone
          <input list="edit-zones" value={timezone} onChange={(e) => setTimezone(e.target.value)} required />
          <datalist id="edit-zones">
            {zones().map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
        </label>
        {timezone !== boat.timezone && <p className="hint">Trips keep their moment in time. A new time zone changes the days and hours they are shown on.</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="button" disabled={busy}>
            Save
          </button>
        </div>
      </form>
    </Modal>
  );
}
