import { type FormEvent, useEffect, useState } from 'react'
import {
  createProject,
  deleteProject,
  getProjects,
  type Project,
  updateProject,
} from './api/projects'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; projects: Project[] }
  | { phase: 'error'; message: string }

type FormValues = {
  name: string
  description: string
}

const emptyForm: FormValues = { name: '', description: '' }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function App() {
  const [listState, setListState] = useState<ListState>({ phase: 'loading' })
  const [form, setForm] = useState<FormValues>(emptyForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    getProjects()
      .then((projects) => {
        if (!cancelled) {
          setListState({ phase: 'loaded', projects })
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setListState({
            phase: 'error',
            message: errorMessage(error, 'Unable to load projects.'),
          })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  function startEdit(project: Project) {
    setEditingId(project.id)
    setForm({ name: project.name, description: project.description ?? '' })
    setFormError(null)
  }

  function cancelEdit() {
    setEditingId(null)
    setForm(emptyForm)
    setFormError(null)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!form.name.trim()) {
      setFormError('Name is required.')
      return
    }

    setFormError(null)
    setActionError(null)
    setSubmitting(true)

    const input = {
      name: form.name.trim(),
      description: form.description.trim() === '' ? null : form.description,
    }

    try {
      if (editingId) {
        const updated = await updateProject(editingId, input)
        setListState((state) =>
          state.phase === 'loaded'
            ? {
                phase: 'loaded',
                projects: state.projects.map((project) =>
                  project.id === updated.id ? updated : project,
                ),
              }
            : state,
        )
      } else {
        const created = await createProject(input)
        setListState((state) =>
          state.phase === 'loaded'
            ? { phase: 'loaded', projects: [...state.projects, created] }
            : { phase: 'loaded', projects: [created] },
        )
      }
      setEditingId(null)
      setForm(emptyForm)
    } catch (error) {
      setActionError(
        errorMessage(error, editingId ? 'Failed to update project.' : 'Failed to create project.'),
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(id: string) {
    setDeletingId(id)
    setActionError(null)

    try {
      await deleteProject(id)
      setListState((state) =>
        state.phase === 'loaded'
          ? { phase: 'loaded', projects: state.projects.filter((project) => project.id !== id) }
          : state,
      )
      if (editingId === id) {
        cancelEdit()
      }
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete project.'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <h1>Projects</h1>

      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="project-name">Name</label>
          <input
            id="project-name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </div>
        <div>
          <label htmlFor="project-description">Description</label>
          <input
            id="project-description"
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
        </div>
        {formError && <p role="alert">{formError}</p>}
        <button type="submit" disabled={submitting}>
          {editingId ? 'Save' : 'New Project'}
        </button>
        {editingId && (
          <button type="button" onClick={cancelEdit} disabled={submitting}>
            Cancel
          </button>
        )}
      </form>

      {actionError && <p role="alert">{actionError}</p>}

      {listState.phase === 'loading' && <p>Loading...</p>}
      {listState.phase === 'error' && <p>{listState.message}</p>}
      {listState.phase === 'loaded' && listState.projects.length === 0 && <p>No projects yet.</p>}
      {listState.phase === 'loaded' &&
        listState.projects.map((project) => (
          <div key={project.id}>
            <p>{project.name}</p>
            {project.description && <p>{project.description}</p>}
            <button onClick={() => startEdit(project)}>Edit</button>
            <button onClick={() => handleDelete(project.id)} disabled={deletingId === project.id}>
              Delete
            </button>
          </div>
        ))}
    </>
  )
}

export default App
