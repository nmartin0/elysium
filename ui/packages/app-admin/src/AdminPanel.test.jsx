import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', () => {
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  return {
    listUsers: vi.fn(),
    createUser: vi.fn(),
    disableUser: vi.fn(),
    enableUser: vi.fn(),
    deleteUser: vi.fn(),
    logoutAllForUser: vi.fn(),
    getVisibleSchema: vi.fn(),
    ApiError,
    handleIfSessionExpired: (err, onSessionExpired) => {
      if (err instanceof ApiError && err.status === 401) {
        onSessionExpired()
        return true
      }
      return false
    },
  }
})

import {
  listUsers,
  createUser,
  disableUser,
  enableUser,
  deleteUser,
  logoutAllForUser,
  getVisibleSchema,
  ApiError,
} from '@elysium/shell-api/api'
import AdminPanel from './AdminPanel'

function activeUser(overrides = {}) {
  return { username: 'editoruser', role_name: 'editor', mac_value: 'us-west', disabled: false, ...overrides }
}

function renderPanel(onSessionExpired = vi.fn()) {
  return render(<AdminPanel onSessionExpired={onSessionExpired} />)
}

function userRow(username) {
  return screen.getByText(username).closest('tr')
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AdminPanel -- loading and listing', () => {
  it('shows "Loading…" before listUsers resolves', () => {
    listUsers.mockReturnValue(new Promise(() => {}))
    renderPanel()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('renders username, role, mac_value, and status for each real user', async () => {
    listUsers.mockResolvedValue([activeUser()])
    renderPanel()

    await waitFor(() => expect(screen.getByText('editoruser')).toBeInTheDocument())
    expect(screen.getByText('editor')).toBeInTheDocument()
    expect(screen.getByText('us-west')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('shows an em dash for a null mac_value, not blank or "null"', async () => {
    listUsers.mockResolvedValue([activeUser({ username: 'adminuser', mac_value: null })])
    renderPanel()

    await waitFor(() => expect(screen.getByText('adminuser')).toBeInTheDocument())
    expect(screen.getByText('\u2014')).toBeInTheDocument()
  })

  it('shows "Disabled" status, and an Enable (not Disable) button, for a disabled user', async () => {
    listUsers.mockResolvedValue([activeUser({ disabled: true })])
    renderPanel()

    await waitFor(() => expect(screen.getByText('Disabled')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Enable' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Disable' })).not.toBeInTheDocument()
  })

  it('shows the error message when the initial load fails', async () => {
    listUsers.mockRejectedValue(new ApiError(500, 'Could not load users'))
    renderPanel()

    await waitFor(() => expect(screen.getByText('Could not load users')).toBeInTheDocument())
  })

  it('calls onSessionExpired and shows no error text on a 401 during load', async () => {
    listUsers.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    renderPanel(onSessionExpired)

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
  })
})

describe('AdminPanel -- enable/disable', () => {
  it('clicking Disable calls disableUser and reloads the list', async () => {
    listUsers.mockResolvedValueOnce([activeUser()]).mockResolvedValueOnce([activeUser({ disabled: true })])
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Disable' }))

    await waitFor(() => expect(disableUser).toHaveBeenCalledWith('editoruser'))
    await waitFor(() => expect(listUsers).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByText('Disabled')).toBeInTheDocument())
  })

  it('clicking Enable calls enableUser and reloads the list', async () => {
    listUsers.mockResolvedValueOnce([activeUser({ disabled: true })]).mockResolvedValueOnce([activeUser({ disabled: false })])
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enable' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Enable' }))

    await waitFor(() => expect(enableUser).toHaveBeenCalledWith('editoruser'))
    await waitFor(() => expect(screen.getByText('Active')).toBeInTheDocument())
  })

  it('shows the error message when disabling fails, without reloading the list', async () => {
    listUsers.mockResolvedValue([activeUser()])
    disableUser.mockRejectedValue(new ApiError(500, 'Could not disable user'))
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Disable' }))

    await waitFor(() => expect(screen.getByText('Could not disable user')).toBeInTheDocument())
    expect(listUsers).toHaveBeenCalledTimes(1)
  })

  it('calls onSessionExpired and shows no error text on a 401 while disabling', async () => {
    listUsers.mockResolvedValue([activeUser()])
    disableUser.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    renderPanel(onSessionExpired)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Disable' }))

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
  })
})

describe('AdminPanel -- log out sessions', () => {
  it('clicking "Log out sessions" calls logoutAllForUser and reloads', async () => {
    listUsers.mockResolvedValue([activeUser()])
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Log out sessions' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Log out sessions' }))

    await waitFor(() => expect(logoutAllForUser).toHaveBeenCalledWith('editoruser'))
    await waitFor(() => expect(listUsers).toHaveBeenCalledTimes(2))
  })
})

describe('AdminPanel -- view/hide schema', () => {
  it('clicking "View schema" fetches and shows the real schema as JSON', async () => {
    listUsers.mockResolvedValue([activeUser()])
    getVisibleSchema.mockResolvedValue({ Customer: { fields: { name: { type: 'data' } } } })
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'View schema' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'View schema' }))

    await waitFor(() => expect(getVisibleSchema).toHaveBeenCalledWith('editoruser'))
    await waitFor(() => expect(screen.getByText(/"Customer"/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Hide schema' })).toBeInTheDocument()
  })

  it('clicking "Hide schema" hides it again WITHOUT a new API call', async () => {
    listUsers.mockResolvedValue([activeUser()])
    getVisibleSchema.mockResolvedValue({ Customer: {} })
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'View schema' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'View schema' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Hide schema' })).toBeInTheDocument())
    getVisibleSchema.mockClear()

    fireEvent.click(screen.getByRole('button', { name: 'Hide schema' }))

    expect(screen.queryByText(/"Customer"/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View schema' })).toBeInTheDocument()
    expect(getVisibleSchema).not.toHaveBeenCalled()
  })

  it('shows the error message when fetching the schema fails', async () => {
    listUsers.mockResolvedValue([activeUser()])
    getVisibleSchema.mockRejectedValue(new ApiError(500, 'Could not load schema'))
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'View schema' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'View schema' }))

    await waitFor(() => expect(screen.getByText('Could not load schema')).toBeInTheDocument())
  })

  it("two different users' own schema toggles operate independently", async () => {
    listUsers.mockResolvedValue([activeUser(), activeUser({ username: 'adminuser', role_name: 'admin' })])
    getVisibleSchema.mockImplementation(async (username) => ({ owner: username }))
    renderPanel()
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'View schema' })).toHaveLength(2))

    fireEvent.click(within(userRow('editoruser')).getByRole('button', { name: 'View schema' }))

    await waitFor(() => expect(screen.getByText(/"editoruser"/)).toBeInTheDocument())
    // The second user's own toggle is untouched -- still "View schema".
    expect(within(userRow('adminuser')).getByRole('button', { name: 'View schema' })).toBeInTheDocument()
  })
})

describe('AdminPanel -- delete', () => {
  it('shows a real confirm() dialog naming the username before deleting', async () => {
    listUsers.mockResolvedValue([activeUser()])
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(confirmSpy).toHaveBeenCalledWith('Delete editoruser? This cannot be undone.')
    confirmSpy.mockRestore()
  })

  it('calls deleteUser and reloads when the confirm dialog is accepted', async () => {
    listUsers.mockResolvedValue([activeUser()])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(deleteUser).toHaveBeenCalledWith('editoruser'))
    await waitFor(() => expect(listUsers).toHaveBeenCalledTimes(2))
  })

  it('never calls deleteUser when the confirm dialog is dismissed', async () => {
    listUsers.mockResolvedValue([activeUser()])
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPanel()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(deleteUser).not.toHaveBeenCalled()
    expect(listUsers).toHaveBeenCalledTimes(1)
  })
})

describe('AdminPanel -- CreateUserForm', () => {
  beforeEach(() => {
    listUsers.mockResolvedValue([])
  })

  it('renders username, password, mac value, and role inputs, plus a submit button', async () => {
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('MAC value (optional)')).toBeInTheDocument()
    expect(screen.getByLabelText('Role')).toBeInTheDocument()
  })

  it('the password input is genuinely masked', async () => {
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
  })

  it('username, password, and role are required; mac value is not', async () => {
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())
    expect(screen.getByLabelText('Username')).toBeRequired()
    expect(screen.getByLabelText('Password')).toBeRequired()
    expect(screen.getByLabelText('Role')).toBeRequired()
    expect(screen.getByLabelText('MAC value (optional)')).not.toBeRequired()
  })

  it('calls createUser with the real, entered values', async () => {
    createUser.mockResolvedValue(undefined)
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw123456' } })
    fireEvent.change(screen.getByLabelText('MAC value (optional)'), { target: { value: 'us-east' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'editor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(createUser).toHaveBeenCalledWith('newuser', 'pw123456', 'us-east', 'editor'))
  })

  it('clears every field and reloads the user list after a successful create', async () => {
    createUser.mockResolvedValue(undefined)
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw123456' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'editor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(screen.getByLabelText('Username')).toHaveValue(''))
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByLabelText('Role')).toHaveValue('')
    await waitFor(() => expect(listUsers).toHaveBeenCalledTimes(2))
  })

  it('shows "Creating…" and disables the button while the request is in flight', async () => {
    createUser.mockReturnValue(new Promise(() => {}))
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw123456' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'editor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled())
  })

  it('shows the real, specific error message on failure (e.g. an unknown role), and does NOT clear the form', async () => {
    createUser.mockRejectedValue(new ApiError(400, "Unknown role 'editr'"))
    renderPanel()
    await waitFor(() => expect(listUsers).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw123456' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'editr' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(screen.getByText("Unknown role 'editr'")).toBeInTheDocument())
    expect(screen.getByLabelText('Username')).toHaveValue('newuser')
    expect(screen.getByLabelText('Role')).toHaveValue('editr')
  })

  it('calls onSessionExpired and shows no error text on a 401', async () => {
    createUser.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    renderPanel(onSessionExpired)
    await waitFor(() => expect(listUsers).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw123456' } })
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'editor' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
  })
})
