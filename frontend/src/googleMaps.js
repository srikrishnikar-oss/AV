let googleMapsPromise

export function loadGoogleMaps(apiKey) {
  if (!apiKey) {
    return Promise.reject(new Error('Missing Google Maps API key.'))
  }

  if (window.google?.maps) {
    return Promise.resolve(window.google.maps)
  }

  if (googleMapsPromise) {
    return googleMapsPromise
  }

  googleMapsPromise = new Promise((resolve, reject) => {
    const callbackName = '__initGoogleMapsForAV'
    const authFailureName = '__gmAuthFailureForAV'
    let settled = false
    let timeoutId = null

    const cleanup = () => {
      if (timeoutId) {
        window.clearTimeout(timeoutId)
      }
      delete window[callbackName]
      delete window[authFailureName]
    }

    const settleResolve = () => {
      if (settled) return
      settled = true
      cleanup()
      resolve(window.google.maps)
    }

    const settleReject = (error) => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }

    window[callbackName] = () => {
      if (!window.google?.maps) {
        settleReject(new Error('Google Maps loaded without the Maps API.'))
        return
      }
      settleResolve()
    }
    window[authFailureName] = () => {
      settleReject(new Error('Google Maps API key was rejected.'))
    }
    window.gm_authFailure = window[authFailureName]

    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places&callback=${callbackName}`
    script.async = true
    script.defer = true
    script.onerror = () => {
      settleReject(new Error('Failed to load Google Maps script.'))
    }
    timeoutId = window.setTimeout(() => {
      settleReject(new Error('Google Maps script timed out.'))
    }, 12000)
    document.head.appendChild(script)
  })

  return googleMapsPromise
}
