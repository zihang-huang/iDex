import XCTest

@MainActor
final class iDexUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSampleIsIdentifiedByBundledModel() throws {
        let app = launchInEnglish()
        XCTAssertTrue(element("viewfinder", in: app).waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["SAMPLE TARGET"].exists)
        XCTAssertFalse(app.buttons["sample-button"].exists)
        let identify = app.buttons["identify-button"]
        XCTAssertTrue(identify.isEnabled)
        attachScreenshot("scanner-sample-en", app: app)
        identify.tap()

        // The sample follows the camera's Core ML pipeline; no launch argument
        // replaces inference with a canned result.
        XCTAssertTrue(element("scan-result", in: app).waitForExistence(timeout: 45), app.debugDescription)
        XCTAssertEqual(app.staticTexts["scan-result-name"].label, "Pikachu")
        XCTAssertTrue(element("scan-result-sprite", in: app).exists)
        XCTAssertTrue(identify.isEnabled)
        XCTAssertTrue(identify.label.contains("RESCAN"))
        XCTAssertFalse(app.buttons["close-record"].exists)
        attachScreenshot("pikachu-scanner-result", app: app)
        identify.tap()
        XCTAssertTrue(app.staticTexts["SAMPLE TARGET"].waitForExistence(timeout: 5))
        XCTAssertFalse(element("scan-result", in: app).exists)
        XCTAssertTrue(identify.label.contains("SCAN"))
        identify.tap()
        XCTAssertTrue(element("scan-result", in: app).waitForExistence(timeout: 45))
        if !app.buttons["catalog-button"].exists { app.buttons["record-button"].tap() }
        XCTAssertEqual(app.staticTexts["pokemon-name"].label, "Pikachu")
        XCTAssertEqual(app.staticTexts["entry-number"].label, "No. 025")
        XCTAssertTrue(app.buttons["read-button"].exists)
        XCTAssertFalse(element("scan-message", in: app).exists)
        attachScreenshot("pikachu-recognition", app: app)
    }

    func testLanguageSwitchPersistsAcrossLaunches() throws {
        let app = launchInEnglish()
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.buttons["language-zhHans"].waitForExistence(timeout: 5))
        app.buttons["language-zhHans"].tap()
        XCTAssertTrue(app.navigationBars["设备设置"].waitForExistence(timeout: 5))
        app.buttons["settings-done"].tap()
        XCTAssertTrue(app.buttons["identify-button"].label.contains("扫描"))
        attachScreenshot("scanner-zh", app: app)
        app.terminate()

        // This launch reads the persisted selection without a language override.
        app.launchArguments = ["-idex.soundEnabled", "NO"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["identify-button"].label.contains("扫描"))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.navigationBars["设备设置"].waitForExistence(timeout: 5))
        app.buttons["language-en"].tap()
        XCTAssertTrue(app.navigationBars["Device settings"].waitForExistence(timeout: 5))
        app.buttons["settings-done"].tap()
        XCTAssertTrue(app.buttons["identify-button"].label.contains("SCAN"))
    }

    func testRecordFillsCoverDisplayAndCloses() throws {
        let app = launchInEnglish()
        guard !app.buttons["catalog-button"].exists else {
            throw XCTSkip("The expanded display shows the record beside the scanner.")
        }
        for language in ["en", "zhHans", "ja"] {
            if language != "en" {
                app.terminate()
                app.launchArguments = ["-idex.language", language, "-idex.soundEnabled", "NO"]
                app.launch()
            }
            app.buttons["record-button"].tap()
            let number = app.staticTexts["entry-number"]
            XCTAssertTrue(number.waitForExistence(timeout: 5))
            let close = app.buttons["close-record"]
            XCTAssertTrue(close.isHittable)
            attachScreenshot("record-cover-\(language)", app: app)
            XCTAssertGreaterThanOrEqual(number.frame.minY - app.frame.minY, 96)
            XCTAssertTrue(app.frame.contains(close.frame))
            XCTAssertGreaterThan(close.frame.minY, app.frame.minY + app.frame.height * 0.8)
            XCTAssertGreaterThanOrEqual(close.frame.height, 44)
            XCTAssertFalse(close.frame.intersects(app.buttons["catalog-button"].frame))
            XCTAssertFalse(close.frame.intersects(app.buttons["read-button"].frame))
            let footer = app.staticTexts["record-footer"]
            XCTAssertTrue(footer.exists)
            // The footer shares its row with the bottom screws. Both must
            // remain above the shell's 12pt inset decorative line.
            XCTAssertLessThanOrEqual(footer.frame.maxY, app.frame.maxY - 20)
            let statsLabel = ["en": "Toggle base stats", "zhHans": "切换基础能力", "ja": "種族値の表示を切り替える"][language]!
            app.buttons[statsLabel].tap()
            XCTAssertLessThanOrEqual(footer.frame.maxY, app.frame.maxY - 20)
            attachScreenshot("record-cover-stats-\(language)", app: app)
            close.tap()
            XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 5))
        }
    }

    func testJapaneseSelectionPersistsAndLocalizesScannerRecordAndSearch() throws {
        let app = launchInEnglish()
        app.buttons["settings-button"].tap()
        XCTAssertTrue(app.buttons["language-ja"].waitForExistence(timeout: 5))
        app.buttons["language-ja"].tap()
        XCTAssertTrue(app.navigationBars["デバイス設定"].waitForExistence(timeout: 5))
        attachScreenshot("settings-ja", app: app)
        app.buttons["settings-done"].tap()
        XCTAssertTrue(app.buttons["identify-button"].label.contains("スキャン"))
        app.terminate()
        app.launchArguments = ["-idex.soundEnabled", "NO", "-idex.lastViewed", "25"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["identify-button"].label.contains("スキャン"))
        XCTAssertTrue(app.buttons["camera-button"].label.contains("カメラ"))
        attachScreenshot("scanner-ja", app: app)

        app.buttons["identify-button"].tap()
        XCTAssertTrue(element("scan-result", in: app).waitForExistence(timeout: 45))
        XCTAssertEqual(app.staticTexts["scan-result-name"].label, "ピカチュウ")
        XCTAssertTrue(app.buttons["identify-button"].label.contains("再スキャン"))
        if !app.buttons["catalog-button"].exists { app.buttons["record-button"].tap() }
        XCTAssertEqual(app.staticTexts["pokemon-name"].label, "ピカチュウ")
        XCTAssertTrue(app.staticTexts["ねずみポケモン"].exists)
        XCTAssertTrue(app.staticTexts["でんき"].exists)
        app.buttons["種族値の表示を切り替える"].tap()
        XCTAssertTrue(app.staticTexts["こうげき"].exists)
        attachScreenshot("record-stats-ja", app: app)

        openCatalog(in: app, title: "カントー図鑑")
        let search = app.searchFields.firstMatch
        if !search.exists {
            let revealSearch = app.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "検索", "Search")).firstMatch
            XCTAssertTrue(revealSearch.waitForExistence(timeout: 5))
            revealSearch.tap()
        }
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("ピカチュウ")
        XCTAssertTrue(app.buttons["pokemon-25"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["pokemon-1"].exists)
        attachScreenshot("catalog-japanese-search", app: app)
        replaceSearchText("ほのお", in: search)
        XCTAssertTrue(app.buttons["pokemon-6"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["pokemon-25"].exists)
        app.buttons["pokemon-6"].tap()
        XCTAssertEqual(app.staticTexts["pokemon-name"].label, "リザードン")
        attachScreenshot("charizard-record-ja", app: app)
    }

    func testCatalogSearchAcceptsEnglishChineseAndDexNumber() throws {
        let app = launchInEnglish()
        openCatalog(in: app)
        let search = app.searchFields.firstMatch
        if !search.exists {
            // iOS 27 can present .searchable as a bottom search button until used.
            let revealSearch = app.buttons["Search"]
            XCTAssertTrue(revealSearch.waitForExistence(timeout: 5))
            revealSearch.tap()
        }
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("Pikachu")
        let pikachu = app.buttons["pokemon-25"]
        XCTAssertTrue(pikachu.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["pokemon-1"].exists)
        attachScreenshot("catalog-english-search", app: app)

        replaceSearchText("皮卡丘", in: search)
        XCTAssertTrue(pikachu.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["pokemon-1"].exists)
        replaceSearchText("006", in: search)
        let charizard = app.buttons["pokemon-6"]
        XCTAssertTrue(charizard.waitForExistence(timeout: 5))
        XCTAssertFalse(pikachu.exists)
        charizard.tap()

        XCTAssertTrue(app.staticTexts["pokemon-name"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["pokemon-name"].label, "Charizard")
        XCTAssertEqual(app.staticTexts["entry-number"].label, "No. 006")
        XCTAssertTrue(app.staticTexts["ARCHIVE"].exists)
        attachScreenshot("charizard-archive", app: app)
    }

    func testTurningPhoneDoesNotRotateScannerOrPresentations() throws {
        XCUIDevice.shared.orientation = .portrait
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launchInEnglish()
        let scanner = element("viewfinder", in: app)
        XCTAssertTrue(scanner.waitForExistence(timeout: 10))
        let scannerFrame = scanner.frame
        let appFrame = app.frame
        let expanded = app.buttons["catalog-button"].exists

        for orientation in [UIDeviceOrientation.landscapeLeft, .landscapeRight, .portraitUpsideDown, .portrait] {
            XCUIDevice.shared.orientation = orientation
            XCTAssertEqual(app.frame.width, appFrame.width, accuracy: 1)
            XCTAssertEqual(app.frame.height, appFrame.height, accuracy: 1)
            XCTAssertEqual(scanner.frame.minX, scannerFrame.minX, accuracy: 1)
            XCTAssertEqual(scanner.frame.minY, scannerFrame.minY, accuracy: 1)
            XCTAssertEqual(scanner.frame.width, scannerFrame.width, accuracy: 1)
            XCTAssertEqual(scanner.frame.height, scannerFrame.height, accuracy: 1)
            XCTAssertEqual(app.buttons["catalog-button"].exists, expanded)
        }
        attachScreenshot(expanded ? "orientation-locked-expanded" : "orientation-locked-cover", app: app)

        if !expanded { app.buttons["record-button"].tap() }
        let name = app.staticTexts["pokemon-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        let recordFrame = name.frame
        for orientation in [UIDeviceOrientation.landscapeLeft, .landscapeRight, .portrait] {
            XCUIDevice.shared.orientation = orientation
            XCTAssertEqual(app.frame.width, appFrame.width, accuracy: 1)
            XCTAssertEqual(app.frame.height, appFrame.height, accuracy: 1)
            XCTAssertEqual(name.frame.minX, recordFrame.minX, accuracy: 1)
            XCTAssertEqual(name.frame.minY, recordFrame.minY, accuracy: 1)
            if !expanded { XCTAssertTrue(app.buttons["close-record"].isHittable) }
        }
        attachScreenshot("orientation-locked-record", app: app)

        openCatalog(in: app)
        assertPresentationDoesNotRotate("National archive", app: app, appFrame: appFrame)
        app.buttons["settings-done"].tap()
        if !expanded { app.buttons["close-record"].tap() }

        app.buttons["settings-button"].tap()
        assertPresentationDoesNotRotate("Device settings", app: app, appFrame: appFrame)
        app.buttons["settings-done"].tap()
    }

    func testLaunchingWhileTurnedKeepsTheNativeLayout() throws {
        defer { XCUIDevice.shared.orientation = .portrait }
        XCUIDevice.shared.orientation = .portrait
        let app = launchInEnglish()
        let nativeFrame = app.frame
        app.terminate()

        for orientation in [UIDeviceOrientation.landscapeLeft, .landscapeRight, .portraitUpsideDown] {
            XCUIDevice.shared.orientation = orientation
            app.launch()
            XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 10))
            XCTAssertEqual(app.frame.width, nativeFrame.width, accuracy: 1)
            XCTAssertEqual(app.frame.height, nativeFrame.height, accuracy: 1)
            app.terminate()
        }
    }

    private func assertPresentationDoesNotRotate(_ title: String, app: XCUIApplication, appFrame: CGRect) {
        let navigationBar = app.navigationBars[title]
        XCTAssertTrue(navigationBar.waitForExistence(timeout: 5))
        let frame = navigationBar.frame
        for orientation in [UIDeviceOrientation.landscapeLeft, .landscapeRight, .portraitUpsideDown, .portrait] {
            XCUIDevice.shared.orientation = orientation
            XCTAssertEqual(app.frame.width, appFrame.width, accuracy: 1)
            XCTAssertEqual(app.frame.height, appFrame.height, accuracy: 1)
            XCTAssertEqual(navigationBar.frame.minX, frame.minX, accuracy: 1)
            XCTAssertEqual(navigationBar.frame.minY, frame.minY, accuracy: 1)
            XCTAssertEqual(navigationBar.frame.width, frame.width, accuracy: 1)
            XCTAssertEqual(navigationBar.frame.height, frame.height, accuracy: 1)
            XCTAssertTrue(app.buttons["settings-done"].isHittable)
        }
        // Capture the idle presentation so persistent system-overlay behavior
        // can be inspected separately from the preceding interactions.
        Thread.sleep(forTimeInterval: 3.5)
        attachScreenshot("orientation-locked-\(title)", app: app)
    }

    private func launchInEnglish() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-idex.language", "en", "-idex.soundEnabled", "NO"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 10))
        return app
    }

    private func openCatalog(in app: XCUIApplication, title: String = "National archive") {
        let catalog = app.buttons["catalog-button"]
        if !catalog.isHittable {
            app.buttons["record-button"].tap()
        }
        XCTAssertTrue(catalog.waitForExistence(timeout: 5))
        catalog.tap()
        XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 5))
    }

    private func replaceSearchText(_ text: String, in field: XCUIElement) {
        field.tap()
        if let clear = field.buttons.allElementsBoundByIndex.first, clear.isHittable {
            clear.tap()
        } else if let current = field.value as? String {
            field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count))
        }
        field.typeText(text)
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func attachScreenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
