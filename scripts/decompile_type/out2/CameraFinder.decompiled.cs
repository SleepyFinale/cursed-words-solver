using UnityEngine;
using UnityEngine.SceneManagement;

public class CameraFinder : MonoBehaviour
{
	[SerializeField]
	private Canvas _myCanvas;

	[SerializeField]
	private InventoryVisualController _visualController;

	private bool _hasMadeAssignments;

	public void Initialize()
	{
		SceneManager.activeSceneChanged += AssignCameraToCanvas;
		if (!_hasMadeAssignments)
		{
			MakeAssignments();
			_hasMadeAssignments = true;
		}
		AssignCameraToCanvas(default(Scene), default(Scene));
	}

	public void UnsubscribeFromEvents()
	{
		SceneManager.activeSceneChanged -= AssignCameraToCanvas;
	}

	public void MakeAssignments()
	{
		CharacterInfoPanel.SingletonObject = base.gameObject;
		CharacterInfoPanel.SingletonInventoryVisualController = _visualController;
		Object.DontDestroyOnLoad(_myCanvas.gameObject);
	}

	public void AssignCameraToCanvas(Scene sceneMovedFrom, Scene sceneMovedTo)
	{
		_myCanvas.worldCamera = Camera.main;
	}
}
